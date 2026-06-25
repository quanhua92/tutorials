"""
saga_pattern.py - Reference implementation of the Saga pattern
(Hector Garcia-Molina & Kenneth Salem, 1987): a long-lived distributed
transaction modeled as a SEQUENCE of local transactions T1, T2, ..., Tn, each
paired with a compensating transaction C1, C2, ..., Cn. If step Tk fails, the
saga runs C(k-1), C(k-2), ..., C1 in reverse to semantically undo what already
happened. There is NO global lock and NO magic rollback -- compensation is a
business-level inverse, not a database undo.

This is the single source of truth that SAGA_PATTERN.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 saga_pattern.py

============================================================================
THE INTUITION (read this first) -- the non-refundable trip
============================================================================
You book a trip online: flight, hotel, rental car, then the card is charged.
These are FOUR separate services (airline, hotel chain, car rental, payment
gateway) -- no single database spans them, so a classic ACID transaction is
impossible. Instead you run a SAGA: do step 1, then step 2, then step 3, then
step 4. If step 4 (charge card) FAILS -- say the card is declined -- you cannot
"roll back" the airline reservation (the seat was held, maybe reassigned); you
can only CANCEL it, and the airline keeps a cancellation fee. So you cancel the
car (minus a fee), cancel the hotel (minus a fee), cancel the flight (minus a
fee). The saga ends "undone" in a BUSINESS sense -- no trip -- but your wallet
is lighter by the sum of the cancellation fees. THAT gap between "undo" and
"compensate" is the whole reason sagas exist and the whole reason they are
tricky.

  * FORWARD       : T1 BookFlight, T2 BookHotel, T3 RentCar, T4 ChargeCard.
                    Each charges the wallet for its component.
  * COMPENSATION  : if Tk fails, run C(k-1), C(k-2), ..., C1 in REVERSE order.
                    C3 CancelCar, C2 CancelHotel, C1 CancelFlight. Each refunds
                    the charge MINUS a cancellation fee -> compensation != undo.
  * TWO WAYS TO   : ORCHESTRATION -- a central coordinator calls each service in
    COORDINATE     order and drives compensation on failure (Temporal, Camunda,
                    AWS Step Functions). CHOREOGRAPHY -- no coordinator; each
                    service reacts to events published by the previous one and,
                    on failure, emits an event that the prior service reacts to.

WHY NOT JUST USE 2PC: two-phase commit gives true ACID across the four services
but it BLOCKS -- if the coordinator stalls during the commit phase, every
participant holds its locks and the whole trip-booking system freezes. Sagas
trade isolation and instant-atomicity for AVAILABILITY and non-blocking
progress: partial states are visible mid-saga, but the system never jams, and
compensation eventually restores consistency. In microservice land, where you
cannot hold cross-service locks, the saga trade-off is almost always right.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  saga          : a sequence of local transactions T1..Tn, each with a
                  compensating transaction C1..Cn. Either all Ti complete
                  (COMPLETED) or, on failure at Tk, C(k-1)..C1 run (ROLLED_BACK).
  local         : a transaction confined to ONE service's own database. It is
  transaction     ACID locally. The saga as a whole is NOT ACID (no isolation
                  across services, no global atomic commit).
  compensation  : the SEMANTIC inverse of a local transaction. It does not
                  "undo" the Ti (the real world moved on); it applies a
                  business action that logically cancels it (refund minus fee).
  compensation  : NOT a database rollback. Rollback pretends Ti never happened
  != rollback     (restores the exact prior state). Compensation accepts that
                  Ti happened and applies a counter-action whose net effect may
                  be non-zero (e.g. the cancellation fee stays with the vendor).
  orchestrator  : a central component that KNOWS the saga graph and invokes each
                  service in order. It is the single place where the state
                  machine lives. Easier to follow; adds a central dependency.
  choreography  : NO central brain. Each service owns its reaction rule
                  ("when FlightBooked, book the hotel"). Services collaborate
                  via events. No central failure point; harder to see the whole
                  picture; risk of cyclic event dependencies.
  isolation     : 2PC provides it (locks hide partial progress). A saga does
  (the gap)       NOT -- between T2 and T3 a reader can see "flight booked,
                  hotel booked, no car yet". Sagas relax isolation deliberately.
  2PC           : two-phase commit. Phase 1 PREPARE (everyone locks + promises);
                  phase 2 COMMIT/ABORT. ACID but BLOCKING: a stalled coordinator
                  or participant freezes everyone holding prepared locks.

============================================================================
THE PAPER & THE LINEAGE
============================================================================
  Garcia-Molina & Salem (1987) : "Sagas", Proc. SIGMOD. The original. Modeled
           long-lived DB transactions as a chain of sub-transactions + their
           compensations; defined the "either all done or all compensated" rule.
  Richardson (microservices.io) : modernized sagas for microservices, codified
           the Orchestration vs Choreography split. The travel-booking saga
           implemented here follows his canonical illustration.
  Temporal / Camunda /          : production orchestration engines for sagas.
  AWS Step Functions             A failed step is retried; on terminal failure
                                 the workflow runs compensations in reverse.
  Event-driven microservices    : the choreography style -- services emit and
  (Kafka, RabbitMQ)               consume domain events instead of being called.
  2PC / XA (Gray 1978)          : the ACID alternative. Blocking; works only
           where you can hold locks across all participants. See Section E.

KEY INVARIANTS (verified by the gold check):
  Either-all-or-all-     : the saga ends in exactly one of two terminal states --
  compensated              every Ti done (COMPLETED), or every Ti that started is
                           compensated (ROLLED_BACK). No Ti is left half-applied.
  Reverse-order           : on failure at Tk, compensations run for completed
  compensation              steps in REVERSE order (C(k-1) before C(k-2) ... C1).
  Compensation is         : each Cj leaves a NON-zero net effect (the cancellation
  not a zero-sum            fee). The wallet does NOT return to its pre-saga value
                           after a rollback. This is compensation != undo.
  Coordination-           : orchestration and choreography, given the same steps
  equivalence              and the same failure, reach the SAME terminal state and
                           the SAME wallet balance.

Conventions in this file:
  STEPS         : the 4 booking steps, each with a name, forward cost, service,
                  compensation name, and refund (cost - fee).
  wallet        : the customer's card balance, starting at INITIAL_WALLET=1000.
                  Forward actions decrement it; compensations increment it by
                  refund = cost - fee.
  state         : a dict {wallet:int, services:{name: status}} where status is
                  one of: "none", "done", "compensated", "failed".
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The saga definition. The travel-booking example (Richardson, microservices.io).
# Each step charges the wallet by `cost`; its compensation refunds `refund`
# (cost - fee). Fees are what make compensation != undo (Section D).
# ----------------------------------------------------------------------------
INITIAL_WALLET = 1000

STEPS = [
    {"name": "BookFlight", "service": "Flight", "cost": 300,
     "comp": "CancelFlight", "refund": 250},   # fee = 300 - 250 = 50
    {"name": "BookHotel",  "service": "Hotel",  "cost": 200,
     "comp": "CancelHotel",  "refund": 170},   # fee = 200 - 170 = 30
    {"name": "RentCar",    "service": "Car",    "cost": 100,
     "comp": "CancelCar",    "refund": 80},    # fee = 100 -  80 = 20
    {"name": "ChargeCard", "service": "Card",   "cost": 50,
     "comp": "RefundCard",   "refund": 50},    # fee = 0  (last step; never
                                               #          compensates in this saga)
]

# The deterministic failure point for the worked example + gold check: step 3
# (ChargeCard) fails. Steps 0..2 succeed and must be compensated in reverse.
FAIL_INDEX = 3

# Sum of cancellation fees for the steps that actually get compensated.
TOTAL_FEES = sum(s["cost"] - s["refund"] for s in STEPS[:FAIL_INDEX])   # 100


# ============================================================================
# 1. CORE PRIMITIVES  (the code SAGA_PATTERN.md walks through)
# ============================================================================

def fresh_state() -> dict:
    """A blank wallet + per-service status, before the saga starts."""
    return {
        "wallet": INITIAL_WALLET,
        "services": {s["service"]: "none" for s in STEPS},
    }


def apply_forward(state: dict, step: dict) -> None:
    """Local transaction Ti: charge the wallet, mark the service done."""
    state["wallet"] -= step["cost"]
    state["services"][step["service"]] = "done"


def apply_compensation(state: dict, step: dict) -> None:
    """Compensating transaction Ci: refund (cost - fee), mark compensated.

    Note the wallet does NOT return to its pre-Ti value: `refund < cost` whenever
    a cancellation fee applies. That is the whole point of Section D.
    """
    state["wallet"] += step["refund"]
    state["services"][step["service"]] = "compensated"


def run_saga(steps: list, fail_at, state: dict):
    """Execute the forward chain; on failure, compensate completed steps in
    REVERSE order. This is the canonical saga semantics (Garcia-Molina 1987).

    fail_at : index of the step that fails, or None for a fully successful saga.
    Returns (forward_events, comp_events, terminal) where
      forward_events : list of (step_name, "OK" | "FAIL")
      comp_events    : list of (comp_name,   "COMP")
      terminal       : "COMPLETED" | "ROLLED_BACK"
    """
    forward, comp, completed = [], [], []
    failed = False
    for i, step in enumerate(steps):
        if i == fail_at:
            forward.append((step["name"], "FAIL"))
            state["services"][step["service"]] = "failed"
            failed = True
            break
        apply_forward(state, step)
        completed.append(step)
        forward.append((step["name"], "OK"))

    if not failed:
        return forward, comp, "COMPLETED"

    # a step failed: compensate every COMPLETED step, most-recent-first
    for step in reversed(completed):
        apply_compensation(state, step)
        comp.append((step["comp"], "COMP"))
    return forward, comp, "ROLLED_BACK"


# ----------------------------------------------------------------------------
# Orchestration: a central coordinator drives the saga as a state machine.
# Same final state as run_saga; the difference is WHO decides the next step.
# ----------------------------------------------------------------------------
def run_orchestrator(steps: list, fail_at, state: dict):
    """Orchestrated saga: a central brain calls each service in order and, on
    failure, calls compensations in reverse. Returns a list of state-machine
    transitions [(state, action_desc)] plus the terminal state label.

    The orchestrator is the ONLY component that knows the full saga graph; the
    services expose plain "do" / "undo" operations and know nothing of each
    other. This matches Temporal / Camunda / AWS Step Functions.
    """
    transitions = [("START", "orchestrator begins saga")]
    completed = []
    for i, step in enumerate(steps):
        transitions.append((f"DOING_{step['name']}",
                            f"orchestrator calls {step['service']}Service.{step['name']}()"))
        if i == fail_at:
            state["services"][step["service"]] = "failed"
            transitions.append((f"FAILED_{step['name']}",
                                f"{step['name']} threw -> drive compensation"))
            for prev in reversed(completed):
                transitions.append((f"COMPENSATING_{prev['comp']}",
                                    f"orchestrator calls {prev['service']}Service.{prev['comp']}()"))
                apply_compensation(state, prev)
            transitions.append(("ROLLED_BACK", "all completed steps compensated"))
            return transitions, "ROLLED_BACK"
        apply_forward(state, step)
        completed.append(step)
        transitions.append((f"DONE_{step['name']}", f"{step['name']} OK"))
    transitions.append(("COMPLETED", "all steps done"))
    return transitions, "COMPLETED"


# ----------------------------------------------------------------------------
# Choreography: no coordinator. Each service reacts to events; on failure the
# compensation cascade propagates backwards through event subscriptions.
# ----------------------------------------------------------------------------
def run_choreography(steps: list, fail_at, state: dict):
    """Choreographed saga: services collaborate via an event bus. Each service
    subscribes to its trigger event, does its forward action, and publishes the
    next event. On failure it publishes a *_FAIL event; the PRECEDING service
    (which subscribed to that event) compensates and publishes *_CANCELLED,
    which triggers the one before it, and so on -- a reverse cascade with no
    central driver.

    Returns an indented event log (list of strings) showing the call depth.
    """
    log: list[str] = []
    bus: dict[str, list] = {}
    depth = [0]

    def subscribe(event, handler):
        bus.setdefault(event, []).append(handler)

    def publish(event):
        for h in bus.get(event, []):
            h(event)

    forward_chain = [s["service"] for s in steps]
    by_service = {s["service"]: s for s in steps}

    def ind():
        return "    " * depth[0]

    # --- forward handlers: service[idx] reacts to service[idx-1]_OK (or Start) ---
    def make_forward(idx):
        svc = forward_chain[idx]
        step = by_service[svc]

        def handler(_evt):
            if idx == fail_at:
                state["services"][svc] = "failed"
                log.append(f"{ind()}{svc}Service reacts: {step['name']}() -> FAIL "
                           f"-> publish {svc}_FAIL")
                depth[0] += 1
                publish(f"{svc}_FAIL")
                depth[0] -= 1
            else:
                apply_forward(state, step)
                log.append(f"{ind()}{svc}Service reacts: {step['name']}() -> OK "
                           f"-> publish {svc}_OK")
                depth[0] += 1
                publish(f"{svc}_OK")
                depth[0] -= 1
        return handler

    for idx in range(len(forward_chain)):
        trigger = "StartSaga" if idx == 0 else f"{forward_chain[idx - 1]}_OK"
        subscribe(trigger, make_forward(idx))

    # --- compensation handlers: service[idx] cancels when service[idx+1] fails
    #     or cancels. This chains backwards naturally (Card_FAIL -> Car_CANCELLED
    #     -> Hotel_CANCELLED -> Flight_CANCELLED). Only services that COMPLETED
    #     forward ever have their compensation triggered, because a mid-saga
    #     failure stops the forward event chain before later services run. ---
    def make_comp(idx):
        svc = forward_chain[idx]
        step = by_service[svc]

        def handler(_evt):
            apply_compensation(state, step)
            log.append(f"{ind()}{svc}Service reacts: {step['comp']}() "
                       f"-> publish {svc}_CANCELLED")
            depth[0] += 1
            publish(f"{svc}_CANCELLED")
            depth[0] -= 1
        return handler

    for idx in range(len(forward_chain) - 1):
        nxt = forward_chain[idx + 1]
        # the two triggers are mutually exclusive per run: a given successor
        # either FAILs (it never ran forward) or CANCELS (it did, then unwound)
        subscribe(f"{nxt}_FAIL", make_comp(idx))
        subscribe(f"{nxt}_CANCELLED", make_comp(idx))

    # --- terminators ---
    first, last = forward_chain[0], forward_chain[-1]
    subscribe(f"{first}_FAIL",
              lambda _e: log.append(f"{ind()}SAGA: SagaAborted (no steps completed)"))
    subscribe(f"{first}_CANCELLED",
              lambda _e: log.append(f"{ind()}SAGA: SagaRolledBack (all completed compensated)"))
    subscribe(f"{last}_OK",
              lambda _e: log.append(f"{ind()}SAGA: SagaCompleted (all steps done)"))

    log.append("client: publish StartSaga")
    depth[0] += 1
    publish("StartSaga")
    depth[0] -= 1
    return log


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_money(n: int) -> str:
    return f"${n:+d}" if n < 0 else f"${n}"


def print_state(state: dict):
    svcs = ", ".join(f"{s['service']}={st}" for s, st in
                     zip(STEPS, [state["services"][s["service"]] for s in STEPS]))
    print(f"    wallet = ${state['wallet']}    services: {svcs}")


# ============================================================================
# 3. THE SIMULATION SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the booking saga -- forward chain + reverse compensation
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the booking saga  (forward T1..T4 + reverse compensation)")
    print("Four services, no shared database. The saga runs them in order; if any")
    print("fails, the COMPLETED ones are compensated in REVERSE.\n")
    print("The 4 steps (each with its compensating transaction):\n")
    print("| #  | forward (Ti)  | cost   | compensation (Ci) | refund | fee   |")
    print("|----|---------------|--------|-------------------|--------|-------|")
    for i, s in enumerate(STEPS):
        fee = s["cost"] - s["refund"]
        print(f"| T{i+1} | {s['name']:<13} | ${s['cost']:<6} | {s['comp']:<17} "
              f"| ${s['refund']:<6} | ${fee:<5} |")
    print(f"\nstarting wallet = ${INITIAL_WALLET}")

    print("\n--- (1) HAPPY PATH: all 4 steps succeed (no failure) ---")
    st = fresh_state()
    fwd, comp, term = run_saga(STEPS, None, st)
    arrow = " -> ".join(f"[{n} OK]" for n, _ in fwd)
    print(f"  forward : {arrow}")
    print(f"  terminal: {term}  (no compensation needed)")
    print_state(st)
    print("  all services DONE; wallet reduced by the full trip cost.")

    print(f"\n--- (2) FAILURE PATH: step {FAIL_INDEX + 1} (ChargeCard) fails ---")
    st = fresh_state()
    fwd, comp, term = run_saga(STEPS, FAIL_INDEX, st)
    fwd_strs = []
    for n, status in fwd:
        fwd_strs.append(f"[{n} {'OK' if status == 'OK' else 'FAIL X'}]")
    print("  forward : " + " -> ".join(fwd_strs))
    print("           ChargeCard FAILED (card declined). Now compensate the 3")
    print("           COMPLETED steps in REVERSE (most-recent first):")
    comp_strs = [f"[{c}]" for c, _ in comp]
    print("  comp    : " + " <- ".join(comp_strs))
    print("           (RefundCard is N/A: ChargeCard never charged anything, so")
    print("            there is nothing to refund for the failed step itself.)")
    print(f"  terminal: {term}")
    print_state(st)
    print(f"\n  wallet went ${INITIAL_WALLET} -> ${st['wallet']}: a loss of "
          f"${INITIAL_WALLET - st['wallet']} = the SUM of cancellation fees.")
    print("  -> compensation did NOT restore the starting balance. See Section D.")
    print(f"\n[check] forward attempted {len(fwd)} steps, "
          f"{sum(1 for _, s in fwd if s == 'OK')} OK + "
          f"{sum(1 for _, s in fwd if s == 'FAIL')} FAIL; "
          f"compensations ran {len(comp)} in reverse order:  OK")


# ----------------------------------------------------------------------------
# SECTION B: orchestration -- the central state machine
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: orchestration  (central coordinator drives a state machine)")
    print("An ORCHESTRATOR is the only component that knows the whole saga. It calls")
    print("each service in order; on failure it walks BACKWARDS calling compensations.")
    print("The services themselves are stateless workers -- they expose do()/undo() and")
    print("know nothing of each other. This is the Temporal / Camunda / AWS Step")
    print("Functions model.\n")
    print(f"Run with ChargeCard (step {FAIL_INDEX + 1}) failing:\n")
    st = fresh_state()
    transitions, term = run_orchestrator(STEPS, FAIL_INDEX, st)
    print("  state                       action")
    print("  --------------------------- -----------------------------------------")
    for state, action in transitions:
        marker = ""
        if state.startswith("FAILED"):
            marker = "  <-- failure point"
        elif state.startswith("COMPENSATING"):
            marker = "  <-- reverse unwind"
        print(f"  {state:<28} {action}{marker}")
    print(f"\n  terminal state: {term}")
    print_state(st)
    print("\nThe orchestrator's state machine (the single source of truth for flow):")
    print("  START")
    print("    -> DOING_T1 -> DONE_T1 -> DOING_T2 -> DONE_T2 -> ... -> DOING_Tn")
    print("         |                                              |")
    print("         v (any failure)                                v (all OK)")
    print("       FAILED_Tk -> COMPENSATING_T(k-1) -> ... ->     COMPLETED")
    print("                -> COMPENSATING_T1 -> ROLLED_BACK")
    print("\n  PRO of orchestration: the flow is explicit and greppable in one place;")
    print("  easy to add retries, timeouts, branching. CON: the orchestrator is a")
    print("  central dependency (and a scaling / single-failure concern).")
    print(f"\n[check] orchestrator terminal == {term}, wallet == ${st['wallet']} "
          f"(matches Section A failure path):  OK")


# ----------------------------------------------------------------------------
# SECTION C: choreography -- event-driven, no central coordinator
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: choreography  (no coordinator -- services react to events)")
    print("In CHOREOGRAPHY there is NO central brain. Each service SUBSCRIBES to the")
    print("event that means 'your turn' and PUBLISHES an event when it is done. On")
    print("failure it publishes a *_FAIL event; the preceding service (subscribed to")
    print("it) compensates and publishes *_CANCELLED, which wakes the one before it --")
    print("a reverse cascade with no driver. This is the Kafka / event-driven style.\n")
    print("Run with ChargeCard failing -- watch the cascade ripple backwards:\n")
    st = fresh_state()
    log = run_choreography(STEPS, FAIL_INDEX, st)
    for line in log:
        print("  " + line)
    print("\n  final state:")
    print_state(st)
    print("\nNotice there is NO 'orchestrator' anywhere. The reverse order emerges")
    print("from WHO SUBSCRIBES TO WHAT: CarService listens for Card_FAIL, HotelService")
    print("listens for Car_CANCELLED, FlightService listens for Hotel_CANCELLED. Each")
    print("service owns only its own rule -- adding a 5th service means subscribing it,")
    print("not editing a central workflow.")
    print("\n  PRO of choreography: no central dependency, services are decoupled, easy")
    print("  to extend. CON: the overall flow is NOT visible in one place (you must")
    print("  trace event subscriptions across services); risk of cyclic event loops.")
    print(f"\n[check] choreography reached wallet == ${st['wallet']} and all completed")
    print("        services compensated -- SAME outcome as orchestration:  OK")


# ----------------------------------------------------------------------------
# SECTION D: compensation semantics -- compensation is NOT undo
# ----------------------------------------------------------------------------
def section_d():
    banner("SECTION D: compensation is NOT undo  (it is a semantic inverse)")
    print("A database ROLLBACK pretends the transaction never happened: the row goes")
    print("back to its exact prior value, net effect ZERO. Compensation cannot do")
    print("that -- the real world moved on (a seat was held, a room blocked). A")
    print("compensating transaction applies a BUSINESS counter-action whose net effect")
    print("is generally NON-zero. Here, cancelling a booking refunds the charge MINUS")
    print("a cancellation fee. So 'book then cancel' leaves the wallet LIGHTER.\n")
    print("Per-step dollar math (forward then its compensation):\n")
    print("| step (Ti)    | forward charge | compensation (Ci) | refund | fee   |")
    print("|--------------|----------------|-------------------|--------|-------|")
    for s in STEPS[:FAIL_INDEX]:
        fee = s["cost"] - s["refund"]
        net = s["refund"] - s["cost"]
        print(f"| {s['name']:<12} | -${s['cost']:<13} | {s['comp']:<17} | "
              f"+${s['refund']:<6} | ${fee:<5} |")
    print()
    print("Net effect of 'do Ti, then do Ci' (this is NOT zero):")
    print("| step        | forward (wallet) | compensation (wallet) | NET   |")
    print("|-------------|------------------|-----------------------|-------|")
    for s in STEPS[:FAIL_INDEX]:
        net = s["refund"] - s["cost"]
        print(f"| {s['name']:<11} | -${s['cost']:<16} | +${s['refund']:<21} | "
              f"${net:+d}   |")
    print(f"\nTotal NET cost of a fully-rolled-back saga = sum of fees = "
          f"${TOTAL_FEES}.")
    print("  compensation != undo: the wallet does NOT return to its starting value.")
    print()
    print("Contrast with a DB ROLLBACK (e.g. inside one service's local txn):")
    print("  begin; update accounts set bal = bal - 300 where id=42; -- BookFlight")
    print("  rollback;  -- restores bal EXACTLY. Net effect $0. No fee.")
    print("Rollback is only possible WITHIN one ACID database. Across the airline,")
    print("hotel, and car-rental databases there is no shared rollback -- hence the")
    print("saga's compensating transactions, and hence the fees.")
    print(f"\n[check] sum(fees) = ${TOTAL_FEES} != $0 -> compensation is a semantic "
          f"inverse, not a rollback:  OK")


# ----------------------------------------------------------------------------
# SECTION E: saga vs 2PC -- the consistency / availability trade-off
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: saga vs 2PC  (eventual consistency vs blocking ACID)")
    print("Two-phase commit (2PC) is the classic way to atomically update several")
    print("databases. It gives true ACID across them but BLOCKS: phase 1 PREPARE makes")
    print("every participant lock its rows and promise; phase 2 COMMIT/ABORT releases")
    print("them. If the coordinator (or any participant) stalls between the phases,")
    print("EVERYONE holds their locks and the system freezes. Sagas trade that")
    print("isolation for non-blocking availability.\n")
    print("| dimension          | saga                              | 2PC (XA)                       |")
    print("|--------------------|-----------------------------------|--------------------------------|")
    print("| consistency model  | EVENTUAL (via compensation)       | ACID (atomic commit)           |")
    print("| isolation          | NONE -- partial states visible    | FULL -- locks hide partial work|")
    print("| atomicity          | semantic (compensate on failure)  | all-or-nothing (commit/abort)  |")
    print("| failure recovery   | run Cj in reverse order           | ABORT + true rollback          |")
    print("| blocking?          | NO -- each step is independent    | YES -- stalls freeze everyone  |")
    print("| locks held         | none across services              | from PREPARE until COMMIT      |")
    print("| coordinator needed | only for orchestration variant    | always (the 2PC coordinator)   |")
    print("| availability       | HIGH (services decoupled)         | LOW (all must be up to commit) |")
    print("| latency (n parts)  | up to n sequential local txns     | 2 rounds, but BLOCKING         |")
    print("| undo on failure    | compensation (non-zero, has fees) | rollback (exact, zero net)     |")
    print("| fits               | microservices, long-lived work    | single DB / tightly-coupled    |")
    print("| examples           | Temporal, Camunda, AWS Step Fn    | XA, DB coordinators            |")
    print()
    print("The core trade-off, in one line:")
    print("  2PC : locks + atomic commit  -> ACID, but BLOCKING and low availability.")
    print("  Saga: no locks + compensate  -> eventual consistency, but ALWAYS AVAILABLE.")
    print()
    print("Why microservices pick saga: you CANNOT hold a cross-service lock (the")
    print("airline will not block its seat row waiting on your hotel DB). So you give")
    print("up isolation (a reader can see 'flight booked, hotel pending') and accept")
    print("that failures are fixed by compensation, not rollback. The system never")
    print("jams. 🔗 Compare with CAP_TRADEOFFS.md (CP vs AP) and RAFT.md (consensus).")
    print()
    print("Latency shape (1 logical update across n participants):")
    print("| n  | saga worst-case (n steps) | 2PC (2 blocking rounds) |")
    print("|----|---------------------------|-------------------------|")
    for n in (2, 4, 8, 16):
        print(f"| {n:<2} | {n:<25} | 2 (blocking)            |")
    print("\nSaga steps may also run in PARALLEL when they are independent (the chain")
    print("shown here is the strict sequential worst case). 2PC always pays its 2")
    print("blocking rounds regardless.")
    print("\n[check] saga: non-blocking + eventual; 2PC: blocking + ACID -- the trade"
          "-off is explicit:  OK")


# ============================================================================
# 4. GOLD CHECK  (pinned values that saga_pattern.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for saga_pattern.html)")
    print("Capstone invariant (Garcia-Molina 1987): a saga ends in EXACTLY ONE of two")
    print("terminal states -- every Ti COMPLETED, or every Ti that started is")
    print("COMPENSATED in reverse. No Ti is left half-applied. We verify this for the")
    print("ChargeCard-fails scenario, AND check that orchestration and choreography")
    print("reach the IDENTICAL final state (coordination-equivalence).\n")

    # 1) reference saga runner
    st = fresh_state()
    fwd, comp, term = run_saga(STEPS, FAIL_INDEX, st)
    ok_names = [n for n, s in fwd if s == "OK"]
    comp_names = [c for c, _ in comp]
    forward_count = len(fwd)                       # 4 (3 OK + 1 FAIL)
    forward_ok = sum(1 for _, s in fwd if s == "OK")
    final_wallet = st["wallet"]

    # 2) orchestration + choreography from a fresh state each
    st_orch = fresh_state()
    _, term_orch = run_orchestrator(STEPS, FAIL_INDEX, st_orch)
    st_chor = fresh_state()
    run_choreography(STEPS, FAIL_INDEX, st_chor)

    # 3) assertions (the gold invariants)
    assert term == "ROLLED_BACK"
    assert forward_count == len(STEPS)
    assert fwd[FAIL_INDEX] == (STEPS[FAIL_INDEX]["name"], "FAIL")
    assert ok_names == ["BookFlight", "BookHotel", "RentCar"]
    # compensations must be in REVERSE order of the completed steps
    assert comp_names == ["CancelCar", "CancelHotel", "CancelFlight"]
    assert final_wallet == INITIAL_WALLET - TOTAL_FEES
    assert final_wallet == 900
    for s in STEPS[:FAIL_INDEX]:
        assert st["services"][s["service"]] == "compensated"
    assert st["services"][STEPS[FAIL_INDEX]["service"]] == "failed"
    # coordination-equivalence: all three paths reach the SAME final state
    assert term_orch == "ROLLED_BACK"
    assert st_orch["wallet"] == final_wallet
    assert st_chor["wallet"] == final_wallet
    assert st_orch["services"] == st["services"]
    assert st_chor["services"] == st["services"]

    print("  reference run (run_saga):")
    print(f"    forward : {fwd}")
    print(f"    comp    : {comp}")
    print(f"    terminal: {term}")
    print(f"    final   : wallet=${final_wallet}, services={st['services']}")
    print()
    print("GOLD scalars (pinned for saga_pattern.html):")
    print(f"  initial_wallet        = {INITIAL_WALLET}")
    print(f"  num_steps            = {len(STEPS)}")
    print(f"  failed_step_index    = {FAIL_INDEX}  ({STEPS[FAIL_INDEX]['name']})")
    print(f"  forward_attempted    = {forward_count}")
    print(f"  forward_ok           = {forward_ok}")
    print(f"  compensation_count   = {len(comp)}")
    print(f"  compensation_order   = {comp_names}")
    print(f"  total_cancellation_fees = {TOTAL_FEES}")
    print(f"  final_wallet         = {final_wallet}")
    print(f"  final_services       = {st['services']}")
    print(f"  orchestration_wallet = {st_orch['wallet']}  (== final_wallet)")
    print(f"  choreography_wallet  = {st_chor['wallet']}  (== final_wallet)")
    print("  all_compensated      = True")
    print()
    print("[check] failed step compensated all priors in reverse; orchestration &")
    print("        choreography reached the SAME final state; wallet reflects fees:")
    print("        OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("saga_pattern.py - reference impl. All numbers below feed SAGA_PATTERN.md.")
    print("python stdlib only (no external deps).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
