#!/usr/bin/env python3
"""Parking Lot System — Low-Level Design.

Ground-truth OOD implementation. Pure Python stdlib only.

Domain model: a multi-floor parking lot with a Vehicle hierarchy, four
ParkingSpot subtypes, a Strategy-based fee engine, and Entry/Exit terminal
services. Concurrency is guarded by per-spot locks (granularity matches the
contention unit). ParkingLot is a Singleton facade over floors + spots.

Companion artifacts:
    PARKING_LOT.md                   — design guide (UML, SOLID, tradeoffs)
    parking_lot.html                 — interactive visualizer + fee calculator
    parking_lot_output.txt           — captured stdout

Bundle catalog entry #06 in lowleveldesign/.
"""

from __future__ import annotations

import itertools
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


# =============================================================================
# CLOCK - injectable simulated time so demos are deterministic (no real sleeps)
# =============================================================================

class Clock:
    """Injectable clock. Unit is HOURS, so fee math stays in hourly terms."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, hours: float) -> None:
        self._now += hours


# =============================================================================
# VEHICLE hierarchy - abstract base + three concrete types.
# Open/Closed: a new vehicle type means a new subclass, never an edited switch.
# =============================================================================

class Vehicle(ABC):
    """A vehicle seeking a compatible spot. Identity = license plate."""

    def __init__(self, license_plate: str) -> None:
        self.license_plate = license_plate

    @property
    @abstractmethod
    def vehicle_type(self) -> str:
        ...

    def __repr__(self) -> str:
        return f"{self.vehicle_type}({self.license_plate})"


class Motorcycle(Vehicle):
    @property
    def vehicle_type(self) -> str:
        return "Motorcycle"


class Car(Vehicle):
    @property
    def vehicle_type(self) -> str:
        return "Car"


class Truck(Vehicle):
    @property
    def vehicle_type(self) -> str:
        return "Truck"


# =============================================================================
# PARKING SPOT hierarchy - abstract base + four concrete types.
# Each subclass owns its compatibility rule (can_fit). The park()/leave()
# mutation is guarded by a per-spot lock: the lock granularity matches the
# contention unit, so two threads never take the same spot.
# =============================================================================

class ParkingSpot(ABC):
    """A physical spot. Free or holding exactly one vehicle."""

    def __init__(self, spot_id: str) -> None:
        self.spot_id = spot_id
        self._vehicle: Optional[Vehicle] = None
        self._lock = threading.Lock()

    @property
    @abstractmethod
    def spot_type(self) -> str:
        ...

    @property
    def is_free(self) -> bool:
        return self._vehicle is None

    @property
    def vehicle(self) -> Optional[Vehicle]:
        return self._vehicle

    @abstractmethod
    def can_fit(self, vehicle: Vehicle) -> bool:
        ...

    def park(self, vehicle: Vehicle) -> bool:
        """Atomically occupy this spot if free and compatible. Returns success."""
        with self._lock:
            if self._vehicle is not None or not self.can_fit(vehicle):
                return False
            self._vehicle = vehicle
            return True

    def leave(self) -> Optional[Vehicle]:
        with self._lock:
            v = self._vehicle
            self._vehicle = None
            return v


class MotorcycleSpot(ParkingSpot):
    @property
    def spot_type(self) -> str:
        return "Motorcycle"

    def can_fit(self, vehicle: Vehicle) -> bool:
        return vehicle.vehicle_type == "Motorcycle"


class CompactSpot(ParkingSpot):
    @property
    def spot_type(self) -> str:
        return "Compact"

    def can_fit(self, vehicle: Vehicle) -> bool:
        # Spot-upsize policy: a motorcycle may take a compact (down-size ok).
        return vehicle.vehicle_type in ("Motorcycle", "Car")


class LargeSpot(ParkingSpot):
    @property
    def spot_type(self) -> str:
        return "Large"

    def can_fit(self, vehicle: Vehicle) -> bool:
        # Large accepts everything - the spot-upsize target of last resort.
        return vehicle.vehicle_type in ("Motorcycle", "Car", "Truck")


class HandicappedSpot(ParkingSpot):
    @property
    def spot_type(self) -> str:
        return "Handicapped"

    def can_fit(self, vehicle: Vehicle) -> bool:
        # Permit check elided for the demo; a real system gates on a permit flag.
        return True


# =============================================================================
# PARKING FLOOR - a level holding an ordered list of spots.
# =============================================================================

class ParkingFloor:
    def __init__(self, floor_number: int) -> None:
        self.floor_number = floor_number
        self._spots: List[ParkingSpot] = []

    def add_spot(self, spot: ParkingSpot) -> None:
        self._spots.append(spot)

    @property
    def spots(self) -> List[ParkingSpot]:
        return list(self._spots)

    def available_for(self, vehicle: Vehicle) -> List[ParkingSpot]:
        # Snapshot taken outside the spot locks; the per-spot park() is the
        # real guard against the race between scan and acquire.
        return [s for s in self._spots if s.is_free and s.can_fit(vehicle)]

    def count_by_type(self) -> Dict[str, Tuple[int, int]]:
        """Return {spot_type: (free, total)} for this floor."""
        out: Dict[str, Tuple[int, int]] = {}
        for spot in self._spots:
            free, total = out.get(spot.spot_type, (0, 0))
            out[spot.spot_type] = (free + (1 if spot.is_free else 0), total + 1)
        return out


# =============================================================================
# TICKET - proof of an active or completed parking session.
# Distinct from a Reservation (which can exist before arrival): a Ticket is
# created only when a vehicle actually takes a spot.
# =============================================================================

class Ticket:
    def __init__(
        self,
        ticket_id: str,
        vehicle: Vehicle,
        spot: ParkingSpot,
        floor: ParkingFloor,
        entry_time: float,
    ) -> None:
        self.ticket_id = ticket_id
        self.vehicle = vehicle
        self.spot = spot
        self.floor = floor
        self.entry_time = entry_time
        self.exit_time: Optional[float] = None
        self.fee: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def duration_hours(self) -> float:
        end = self.exit_time if self.exit_time is not None else self.entry_time
        return round(end - self.entry_time, 4)


# =============================================================================
# FEE STRATEGY - the price engine. Strategy pattern: pick the rule at runtime.
# A daily cap is composed over hourly; premium multiplies hourly. Each new
# pricing rule is a new class - existing classes never change (Open/Closed).
# =============================================================================

class FeeStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def calculate_fee(self, ticket: Ticket) -> float:
        ...


class HourlyFeeStrategy(FeeStrategy):
    """rate_per_hour * hours, keyed by vehicle type."""

    RATES: Dict[str, float] = {"Motorcycle": 1.0, "Car": 2.0, "Truck": 3.0}

    @property
    def name(self) -> str:
        return "Hourly"

    def rate_for(self, vehicle_type: str) -> float:
        return self.RATES.get(vehicle_type, 2.0)

    def calculate_fee(self, ticket: Ticket) -> float:
        return round(self.rate_for(ticket.vehicle.vehicle_type) * ticket.duration_hours, 2)


class DailyFeeStrategy(FeeStrategy):
    """Hourly fee floored at a per-vehicle-type daily cap."""

    DAILY_CAP: Dict[str, float] = {"Motorcycle": 8.0, "Car": 15.0, "Truck": 25.0}

    def __init__(self, hourly: HourlyFeeStrategy) -> None:
        self._hourly = hourly

    @property
    def name(self) -> str:
        return "Daily"

    def cap_for(self, vehicle_type: str) -> float:
        return self.DAILY_CAP.get(vehicle_type, 15.0)

    def calculate_fee(self, ticket: Ticket) -> float:
        base = self._hourly.calculate_fee(ticket)
        return round(min(base, self.cap_for(ticket.vehicle.vehicle_type)), 2)


class PremiumFeeStrategy(FeeStrategy):
    """Hourly fee scaled by a location/peak multiplier (e.g. downtown, events)."""

    def __init__(self, hourly: HourlyFeeStrategy, multiplier: float = 1.5) -> None:
        self._hourly = hourly
        self._multiplier = multiplier

    @property
    def name(self) -> str:
        return "Premium"

    def calculate_fee(self, ticket: Ticket) -> float:
        return round(self._hourly.calculate_fee(ticket) * self._multiplier, 2)


# =============================================================================
# PARKING LOT - Singleton facade over floors + tickets + spot allocation.
# Clients talk to the lot, never to individual spots directly.
# =============================================================================

class ParkingLot:
    _instance: Optional["ParkingLot"] = None

    def __new__(cls) -> "ParkingLot":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._floors: List[ParkingFloor] = []
        self._tickets: Dict[str, Ticket] = {}
        self._counter = itertools.count(1)

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton (tests build a fresh lot each time)."""
        cls._instance = None

    @property
    def floors(self) -> List[ParkingFloor]:
        return list(self._floors)

    @property
    def tickets(self) -> List[Ticket]:
        return list(self._tickets.values())

    def add_floor(self, floor: ParkingFloor) -> None:
        self._floors.append(floor)

    def _next_ticket_id(self) -> str:
        return f"T-{next(self._counter):04d}"

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        return self._tickets.get(ticket_id)

    def find_available_spots(self, vehicle: Vehicle) -> List[Tuple[ParkingFloor, ParkingSpot]]:
        """Snapshot of every compatible free spot, floor by floor."""
        out: List[Tuple[ParkingFloor, ParkingSpot]] = []
        for floor in self._floors:
            for spot in floor.available_for(vehicle):
                out.append((floor, spot))
        return out

    def park(self, vehicle: Vehicle, clock: Clock) -> Optional[Ticket]:
        # Try every candidate; the per-spot lock is the guard against a race.
        for floor, spot in self.find_available_spots(vehicle):
            if spot.park(vehicle):
                ticket = Ticket(
                    self._next_ticket_id(), vehicle, spot, floor, clock.now()
                )
                self._tickets[ticket.ticket_id] = ticket
                return ticket
        return None

    def leave(self, ticket_id: str, clock: Clock, strategy: FeeStrategy) -> Optional[float]:
        ticket = self._tickets.get(ticket_id)
        if ticket is None or not ticket.is_open:
            return None
        ticket.exit_time = clock.now()
        ticket.spot.leave()
        ticket.fee = strategy.calculate_fee(ticket)
        return ticket.fee

    def availability(self) -> Dict[int, Dict[str, Tuple[int, int]]]:
        """{floor_number: {spot_type: (free, total)}}."""
        return {f.floor_number: f.count_by_type() for f in self._floors}


# =============================================================================
# ENTRY / EXIT TERMINALS - thin services wrapping the lot + clock.
# =============================================================================

class EntryTerminal:
    def __init__(self, lot: ParkingLot, clock: Clock) -> None:
        self._lot = lot
        self._clock = clock

    def enter(self, vehicle: Vehicle) -> Optional[Ticket]:
        ticket = self._lot.park(vehicle, self._clock)
        if ticket is None:
            print(
                f"    [EntryTerminal] LOT FULL - cannot admit "
                f"{vehicle.license_plate} ({vehicle.vehicle_type})"
            )
            return None
        print(
            f"    [EntryTerminal] {vehicle.license_plate} ({vehicle.vehicle_type}) "
            f"-> spot {ticket.spot.spot_id} ({ticket.spot.spot_type}) "
            f"floor {ticket.floor.floor_number} ticket {ticket.ticket_id}"
        )
        return ticket


class ExitTerminal:
    def __init__(self, lot: ParkingLot, clock: Clock) -> None:
        self._lot = lot
        self._clock = clock

    def exit(self, ticket_id: str, strategy: FeeStrategy) -> Optional[float]:
        fee = self._lot.leave(ticket_id, self._clock, strategy)
        if fee is None:
            print(f"    [ExitTerminal] unknown/closed ticket {ticket_id}")
            return None
        ticket = self._lot.get_ticket(ticket_id)
        print(
            f"    [ExitTerminal] {ticket.vehicle.license_plate} "
            f"duration={ticket.duration_hours}h spot={ticket.spot.spot_id} "
            f"fee=${fee:.2f} [{strategy.name}]"
        )
        return fee


# =============================================================================
# DEMO SCENARIOS
# =============================================================================

def _banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n=== {title}\n{line}")


def _build_lot() -> ParkingLot:
    """A two-floor lot: floor 1 (mixed), floor 2 (large + handicapped)."""
    ParkingLot.reset()
    lot = ParkingLot()

    f1 = ParkingFloor(1)
    f1.add_spot(MotorcycleSpot("M1"))
    f1.add_spot(CompactSpot("C1"))
    f1.add_spot(CompactSpot("C2"))
    f1.add_spot(LargeSpot("L1"))

    f2 = ParkingFloor(2)
    f2.add_spot(LargeSpot("L2"))
    f2.add_spot(LargeSpot("L3"))
    f2.add_spot(HandicappedSpot("H1"))

    lot.add_floor(f1)
    lot.add_floor(f2)
    return lot


def demo_hierarchy() -> None:
    _banner("VEHICLE / SPOT HIERARCHY - type matching via can_fit()")
    spots = [
        MotorcycleSpot("M1"),
        CompactSpot("C1"),
        LargeSpot("L1"),
        HandicappedSpot("H1"),
    ]
    vehicles = [Motorcycle("MOTO-1"), Car("CAR-1"), Truck("TRK-1")]

    header = r"  vehicle \ spot |" + "".join(f" {s.spot_type:>11}" for s in spots)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for v in vehicles:
        cells = "".join(f" {'yes':>11}" if s.can_fit(v) else f" {'no':>11}" for s in spots)
        print(f"  {v.vehicle_type:<14} |{cells}")

    # Gold-check: Truck fits ONLY Large.
    fits = {s.spot_type: s.can_fit(Truck("X")) for s in spots}
    assert fits == {"Motorcycle": False, "Compact": False, "Large": True, "Handicapped": True}
    print("[check] OK - Truck accepted only by Large + Handicapped")


def demo_find_and_park() -> None:
    _banner("FIND AVAILABLE SPOTS + PARK - facade drives allocation")
    lot = _build_lot()
    clock = Clock()

    print("  initial availability:")
    for fn, counts in lot.availability().items():
        print(f"    floor {fn}: " + ", ".join(f"{t}={c[0]}/{c[1]}" for t, c in counts.items()))

    for vehicle in [Motorcycle("MOTO-7"), Car("CAR-7"), Truck("TRK-7")]:
        cands = lot.find_available_spots(vehicle)
        print(
            f"  {vehicle.vehicle_type}({vehicle.license_plate}) "
            f"-> {len(cands)} candidate spot(s): "
            + ", ".join(f"{s.spot_id}/{s.spot_type}" for _, s in cands)
        )
        ticket = lot.park(vehicle, clock)
        assert ticket is not None
        print(
            f"    parked at {ticket.spot.spot_id} ({ticket.spot.spot_type}) "
            f"floor {ticket.floor.floor_number} ticket {ticket.ticket_id}"
        )

    # Gold-check: after 3 parks, exactly 3 spots are occupied across the lot.
    occupied = sum(1 for f in lot.floors for s in f.spots if not s.is_free)
    assert occupied == 3, f"expected 3 occupied, got {occupied}"
    print(f"[check] OK - {occupied} spot(s) now occupied after 3 parks")


def demo_fee_strategies() -> None:
    _banner("FEE STRATEGIES - Hourly vs Daily(cap) vs Premium(multiplier)")
    clock = Clock()
    hourly = HourlyFeeStrategy()
    daily = DailyFeeStrategy(hourly)
    premium = PremiumFeeStrategy(hourly, multiplier=1.5)

    print(f"  rates/hr: {hourly.RATES}")
    print(f"  daily cap: {daily.DAILY_CAP}   premium multiplier: 1.5\n")

    # Scenarios: (vehicle, hours, expected_hourly, expected_daily, expected_premium)
    scenarios = [
        (Car("CAR-3"), 3.0, 6.0, 6.0, 9.0),
        (Car("CAR-10"), 10.0, 20.0, 15.0, 30.0),   # 10h @ Car: 20 -> capped at 15
        (Truck("TRK-5"), 5.0, 15.0, 15.0, 22.5),
        (Motorcycle("MOTO-2"), 2.0, 2.0, 2.0, 3.0),
    ]
    print("  vehicle         hours   hourly   daily   premium")
    print("  " + "-" * 52)
    for vehicle, hours, e_h, e_d, e_p in scenarios:
        lot = _build_lot()
        clock = Clock()
        ticket = lot.park(vehicle, clock)
        assert ticket is not None
        clock.advance(hours)
        ticket.exit_time = clock.now()  # close the ticket so duration is exact
        h = hourly.calculate_fee(ticket)
        d = daily.calculate_fee(ticket)
        p = premium.calculate_fee(ticket)
        print(
            f"  {vehicle.vehicle_type:<9}({vehicle.license_plate:<7}) {hours:>5.1f}h "
            f" ${h:>6.2f} ${d:>6.2f} ${p:>7.2f}"
        )
        assert (h, d, p) == (e_h, e_d, e_p), f"fee mismatch for {vehicle}: {(h, d, p)}"
    print("[check] OK - all fees match the predicted Hourly/Daily/Premium values")


def demo_entry_exit() -> None:
    _banner("ENTRY / EXIT TERMINAL - full park -> pay -> leave flow")
    lot = _build_lot()
    clock = Clock()
    entry = EntryTerminal(lot, clock)
    exit_term = ExitTerminal(lot, clock)
    hourly = HourlyFeeStrategy()

    t1 = entry.enter(Car("CAR-42"))
    t2 = entry.enter(Truck("TRK-42"))
    entry.enter(Car("CAR-43"))

    clock.advance(2.5)  # 2.5h pass
    fee1 = exit_term.exit(t1.ticket_id, hourly)
    assert fee1 == 5.0, f"expected $5.00 for 2.5h Car, got {fee1}"

    clock.advance(1.5)  # truck stays 4.0h total
    fee2 = exit_term.exit(t2.ticket_id, hourly)
    assert fee2 == 12.0, f"expected $12.00 for 4.0h Truck, got {fee2}"

    # Gold-check: both spots are free again, one car remains.
    free = sum(1 for f in lot.floors for s in f.spots if s.is_free)
    assert free == 6, f"expected 6 free spots, got {free}"
    print(f"[check] OK - 2 vehicles exited, {free} spots free again (1 remains)")


def demo_spot_upsize() -> None:
    _banner("SPOT-UPSIZE - a Car takes a Large spot when Compact is full")
    ParkingLot.reset()
    lot = ParkingLot()
    floor = ParkingFloor(1)
    # Only one Compact and one Large; fill the Compact first.
    floor.add_spot(CompactSpot("C1"))
    floor.add_spot(LargeSpot("L1"))
    lot.add_floor(floor)
    clock = Clock()

    first = lot.park(Car("CAR-A"), clock)
    second = lot.park(Car("CAR-B"), clock)  # Compact taken -> must upsize to Large
    assert first is not None and second is not None
    print(
        f"  CAR-A -> {first.spot.spot_id} ({first.spot.spot_type}); "
        f"CAR-B -> {second.spot.spot_id} ({second.spot.spot_type}) [upsize]"
    )
    assert first.spot.spot_type == "Compact"
    assert second.spot.spot_type == "Large", "Car should have upsized to Large"

    third = lot.park(Car("CAR-C"), clock)
    print(f"  CAR-C -> {'LOT FULL' if third is None else third.spot.spot_id}")
    assert third is None, "lot should be full for cars now"
    print("[check] OK - Car upsized to Large, then lot correctly reports full")


def demo_concurrency() -> None:
    _banner("CONCURRENCY - per-spot lock prevents double-booking")
    ParkingLot.reset()
    lot = ParkingLot()
    floor = ParkingFloor(1)
    for i in range(5):
        floor.add_spot(LargeSpot(f"L{i + 1}"))  # exactly 5 spots
    lot.add_floor(floor)
    clock = Clock()

    vehicles = [Car(f"CAR-{i:03d}") for i in range(20)]  # 20 cars race for 5 spots
    issued: List[Ticket] = []
    issued_lock = threading.Lock()

    def worker(v: Vehicle) -> None:
        t = lot.park(v, clock)
        if t is not None:
            with issued_lock:
                issued.append(t)

    threads = [threading.Thread(target=worker, args=(v,)) for v in vehicles]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    occupied = sum(1 for s in floor.spots if not s.is_free)
    print(f"  20 threads raced for 5 spots -> {len(issued)} tickets, {occupied} occupied")
    assert len(issued) == 5 and occupied == 5, "double-booking detected!"
    # Each spot holds a distinct vehicle - no aliasing.
    plates = {s.vehicle.license_plate for s in floor.spots if s.vehicle is not None}
    assert len(plates) == 5, "two spots hold the same vehicle!"
    print("[check] OK - exactly 5 tickets, 5 distinct vehicles, no double-booking")


def main() -> None:
    print("PARKING LOT SYSTEM - Low-Level Design")
    print("Vehicle hierarchy | Spot types | Fee strategies | Entry/Exit terminals")
    demo_hierarchy()
    demo_find_and_park()
    demo_fee_strategies()
    demo_entry_exit()
    demo_spot_upsize()
    demo_concurrency()
    print("\n" + "=" * 72)
    print("[check] OK - all parking-lot scenarios demonstrated and verified")
    print("=" * 72)


if __name__ == "__main__":
    main()
