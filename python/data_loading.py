"""
data_loading.py — Bundle #32 (Phase 5).

GOAL (one line): show, by printing every value, that Dataset + DataLoader is the
feeding pipeline — a Dataset yields ONE sample, a DataLoader batches / shuffles /
parallelizes / collates those samples into tensors a model can consume.

This is the GROUND TRUTH for DATA_LOADING.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Deterministic: torch.manual_seed(0) before construction; CPU only; num_workers=0
(multiprocessing order/timing is non-deterministic); a seeded
torch.Generator().manual_seed(0) drives every shuffle.

Run:
    uv run python data_loading.py
"""

from __future__ import annotations

import torch
from torch.utils.data import (
    DataLoader,
    Dataset,
    IterableDataset,
    RandomSampler,
    SequentialSampler,
    get_worker_info,
)

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


# ----------------------------------------------------------------------------
# Reference Datasets (module-level so worker pickling sees clean qualnames).
# ----------------------------------------------------------------------------

class ToyDS(Dataset):
    """A tiny map-style dataset: 8 samples, each a 3-feature vector + scalar
    label. Map-style = implements __len__ + __getitem__."""

    def __init__(self) -> None:
        torch.manual_seed(0)
        self.x = torch.arange(8 * 3, dtype=torch.float32).reshape(8, 3)
        self.y = torch.arange(8, dtype=torch.float32)

    def __len__(self) -> int:
        return self.x.shape[0]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.x[idx], self.y[idx]


class VarLenDS(Dataset):
    """Variable-length token-id sequences — the classic reason to write a
    custom collate_fn (you must pad to a common length before stacking)."""

    def __init__(self) -> None:
        self.seqs = [torch.tensor([1]), torch.tensor([2, 3]),
                     torch.tensor([4, 5, 6]), torch.tensor([7, 8])]

    def __len__(self) -> int:
        return len(self.seqs)

    def __getitem__(self, idx: int) -> torch.Tensor:
        return self.seqs[idx]


class StreamingDS(IterableDataset):
    """Iterable-style dataset: implements __iter__ (NOT __getitem__/__len__).
    Good for streams / data too large to index (DB cursors, sockets, logs)."""

    def __init__(self, n: int) -> None:
        self.n = n

    def __iter__(self):
        for i in range(self.n):
            yield torch.tensor([float(i)])


class NormalizedDS(Dataset):
    """Demonstrates a TRANSFORM applied inside __getitem__: each sample is
    normalized by subtracting the mean and dividing by the std. A transform is
    just a callable; torchvision.transforms.Compose chains them in real code."""

    def __init__(self) -> None:
        torch.manual_seed(0)
        self.x = torch.arange(6, dtype=torch.float32).reshape(6, 1)
        self.mean = self.x.mean()
        self.std = self.x.std()

    def __len__(self) -> int:
        return self.x.shape[0]

    def _transform(self, t: torch.Tensor) -> torch.Tensor:
        return (t - self.mean) / self.std

    def __getitem__(self, idx: int) -> torch.Tensor:
        return self._transform(self.x[idx])


# ----------------------------------------------------------------------------
# Section A — Map-style Dataset: __len__ + __getitem__
# ----------------------------------------------------------------------------

def section_a_map_style_dataset() -> None:
    banner("A — Map-style Dataset: __len__ + __getitem__")
    torch.manual_seed(0)
    ds = ToyDS()

    print("A map-style Dataset subclasses torch.utils.data.Dataset and implements")
    print("__len__() and __getitem__(idx). dataset[idx] returns ONE sample")
    print("(here a (feature_vector, label) tuple). The DataLoader will later")
    print("batch many such samples together.\n")

    print(f"{'isinstance(ds, Dataset)':<36}{isinstance(ds, Dataset)}")
    print(f"{'len(ds)':<36}{len(ds)}")
    one = ds[0]
    print(f"{'ds[0]':<36}{one}")
    print(f"{'type(ds[0]).__name__':<36}{type(one).__name__}")
    print(f"{'ds[0][0].tolist() (features)':<36}{one[0].tolist()}")
    print(f"{'ds[0][1].item() (label)':<36}{one[1].item()}")
    print()

    check("ToyDS is a Dataset subclass", isinstance(ds, Dataset))
    check("len(ds) == 8", len(ds) == 8)
    check("ds[0] is a tuple of two tensors", isinstance(one, tuple))
    check("ds[0][0] has shape (3,) (3 features)", tuple(one[0].shape) == (3,))
    check("ds[0][1] is a scalar tensor", tuple(one[1].shape) == ())


# ----------------------------------------------------------------------------
# Section B — DataLoader: batching + default collate (stacked tensors)
# ----------------------------------------------------------------------------

def section_b_dataloader_default_collate() -> None:
    banner("B — DataLoader batching + default collate (stacked tensors)")
    torch.manual_seed(0)
    ds = ToyDS()
    dl = DataLoader(ds, batch_size=4, shuffle=False)

    print("DataLoader(ds, batch_size=4, shuffle=False) iterates the dataset 4")
    print("samples at a time. The default collate_fn STACKS each field across")
    print("the batch into a new leading dimension: (3,) -> (4,3), () -> (4,).\n")

    print(f"{'type(dl).__name__':<40}{type(dl).__name__!r}")
    print(f"{'len(dl) (num batches)':<40}{len(dl)}")
    print(f"{'dl.batch_size':<40}{dl.batch_size}")
    print(f"{'dl.num_workers':<40}{dl.num_workers}")
    print()

    batches = list(dl)
    xb0, yb0 = batches[0]
    print(f"{'#batches':<40}{len(batches)}")
    print(f"{'batch[0] x shape':<40}{tuple(xb0.shape)}")
    print(f"{'batch[0] y shape':<40}{tuple(yb0.shape)}")
    print(f"{'batch[0] x':<40}{xb0.tolist()}")
    print(f"{'batch[0] y':<40}{yb0.tolist()}")
    xb1, _ = batches[1]
    print(f"{'batch[1] x shape':<40}{tuple(xb1.shape)}")
    print()

    check("DataLoader is iterable", hasattr(dl, "__iter__"))
    check("len(dl) == 2 (8 samples / batch 4)", len(dl) == 2)
    check("batch[0] x shape is (4, 3) (batch dim first)",
          tuple(xb0.shape) == (4, 3))
    check("batch[0] y shape is (4,) (scalar stacked)", tuple(yb0.shape) == (4,))
    check("batch[0] x == first 4 rows of the dataset",
          torch.equal(xb0, ds.x[:4]))
    check("default collate stacked along a NEW leading dim",
          xb0[0].tolist() == ds[0][0].tolist())


# ----------------------------------------------------------------------------
# Section C — Custom collate_fn: padding variable-length sequences
# ----------------------------------------------------------------------------

def _pad_collate(batch: list[torch.Tensor]) -> torch.Tensor:
    """Custom collate: right-pad each sequence to the batch max length, then
    stack. The default collate would FAIL here because the tensors differ in
    their first (and only) dimension."""
    maxlen = max(t.shape[0] for t in batch)
    padded = torch.zeros(len(batch), maxlen, dtype=batch[0].dtype)
    for i, t in enumerate(batch):
        padded[i, : t.shape[0]] = t
    return padded


def section_c_custom_collate_fn() -> None:
    banner("C — Custom collate_fn: padding variable-length sequences")
    torch.manual_seed(0)
    ds = VarLenDS()
    dl = DataLoader(ds, batch_size=4, collate_fn=_pad_collate)

    print("When samples have different shapes, default_collate cannot stack")
    print("them (torch.stack needs matching sizes). A custom collate_fn takes")
    print("the list of samples and returns one batch tensor — here we pad each")
    print("sequence to the batch's max length with zeros, then stack.\n")

    raw = [ds[i] for i in range(len(ds))]
    print(f"{'raw sample lengths':<32}{[t.shape[0] for t in raw]}")
    print(f"{'raw sample[2]':<32}{raw[2].tolist()}")
    print()

    batch = next(iter(dl))
    print(f"{'type(batch).__name__':<32}{type(batch).__name__}")
    print(f"{'batch shape':<32}{tuple(batch.shape)}")
    print(f"{'batch':<32}{batch.tolist()}")
    print()

    check("custom collate produced a single tensor",
          isinstance(batch, torch.Tensor))
    check("batch shape is (4, 3) (4 seqs, max len 3)", tuple(batch.shape) == (4, 3))
    check("seq[2] preserved in row 2", torch.equal(batch[2], raw[2]))
    check("seq[0] padded with zeros to length 3",
          batch[0].tolist() == [1, 0, 0])


# ----------------------------------------------------------------------------
# Section D — Deterministic shuffle: generator=seeded Generator
# ----------------------------------------------------------------------------

def section_d_deterministic_shuffle() -> None:
    banner("D — Deterministic shuffle: generator=seeded Generator")
    torch.manual_seed(0)
    ds = ToyDS()

    print("shuffle=True reshuffles at EVERY epoch. To make the order")
    print("REPRODUCIBLE, pass generator=torch.Generator().manual_seed(seed):")
    print("RandomSampler draws indices from THAT generator, so two loaders")
    print("with the same seed see the identical permutation.\n")

    g1 = torch.Generator().manual_seed(0)
    g2 = torch.Generator().manual_seed(0)
    dl1 = DataLoader(ds, batch_size=4, shuffle=True, generator=g1)
    dl2 = DataLoader(ds, batch_size=4, shuffle=True, generator=g2)

    order1 = [int(v) for _, yb in dl1 for v in yb]
    order2 = [int(v) for _, yb in dl2 for v in yb]
    print(f"{'order with seed=0 (run 1)':<34}{order1}")
    print(f"{'order with seed=0 (run 2)':<34}{order2}")
    print(f"{'orders identical?':<34}{order1 == order2}")

    g3 = torch.Generator().manual_seed(1)
    dl3 = DataLoader(ds, batch_size=4, shuffle=True, generator=g3)
    order3 = [int(v) for _, yb in dl3 for v in yb]
    print(f"{'order with seed=1 (differs)':<34}{order3}")
    print(f"{'seed=0 vs seed=1 identical?':<34}{order1 == order3}")
    print()

    check("same seed -> identical shuffle order", order1 == order2)
    check("different seed -> different order", order1 != order3)
    check("shuffle still covers every index once",
          sorted(order1) == list(range(8)))


# ----------------------------------------------------------------------------
# Section E — Sampler: SequentialSampler vs RandomSampler
# ----------------------------------------------------------------------------

def section_e_sampler() -> None:
    banner("E — Sampler: SequentialSampler vs RandomSampler")
    torch.manual_seed(0)
    ds = ToyDS()

    print("A Sampler yields the index ORDER the loader fetches samples in.")
    print("shuffle=False -> SequentialSampler (0,1,2,...); shuffle=True ->")
    print("RandomSampler. You can also pass a Sampler explicitly, or a")
    print("batch_sampler that yields LISTS of indices per batch.\n")

    seq = list(SequentialSampler(ds))
    rng = list(RandomSampler(ds, generator=torch.Generator().manual_seed(0)))
    print(f"{'list(SequentialSampler(ds))':<40}{seq}")
    print(f"{'list(RandomSampler(ds, seed=0))':<40}{rng}")
    print()

    dl_seq = DataLoader(ds, batch_size=3, sampler=SequentialSampler(ds))
    batch_sampler_idx = list(dl_seq.batch_sampler)
    print(f"{'batch_sampler index lists':<40}{batch_sampler_idx}")
    print()

    check("SequentialSampler yields 0..7 in order", seq == list(range(8)))
    check("RandomSampler is a permutation of all indices",
          sorted(rng) == list(range(8)))
    check("batch_sampler chunks indices by batch_size",
          batch_sampler_idx == [[0, 1, 2], [3, 4, 5], [6, 7]])


# ----------------------------------------------------------------------------
# Section F — IterableDataset: __iter__ for streams
# ----------------------------------------------------------------------------

def section_f_iterable_dataset() -> None:
    banner("F — IterableDataset: __iter__ for streams (no __len__/__getitem__)")
    torch.manual_seed(0)
    ds = StreamingDS(n=5)

    print("An IterableDataset implements __iter__ instead of __getitem__/")
    print("__len__. It yields samples one at a time from a stream. There is no")
    print("random access (no idx), so shuffling/sampling are NOT supported —")
    print("order is whatever __iter__ produces.\n")

    print(f"{'isinstance(ds, IterableDataset)':<38}{isinstance(ds, IterableDataset)}")
    print(f"{'hasattr(ds, \"__getitem__\")':<38}{hasattr(ds, '__getitem__')}")
    print(f"{'hasattr(ds, \"__len__\")':<38}{hasattr(ds, '__len__')}")
    print()

    dl = DataLoader(ds, batch_size=2)
    batches = [b.tolist() for b in dl]
    print(f"{'batches from DataLoader(batch_size=2)':<38}{batches}")
    print()

    check("StreamingDS is an IterableDataset", isinstance(ds, IterableDataset))
    check("IterableDataset has no __len__", not hasattr(ds, "__len__"))
    check("DataLoader batches the stream into pairs",
          batches == [[[0.0], [1.0]], [[2.0], [3.0]], [[4.0]]])


# ----------------------------------------------------------------------------
# Section G — num_workers + pin_memory (conceptual; num_workers=0 for determinism)
# ----------------------------------------------------------------------------

def section_g_workers_and_pinning() -> None:
    banner("G — num_workers + pin_memory (num_workers=0 kept for determinism)")
    torch.manual_seed(0)
    ds = ToyDS()

    print("num_workers>0 spawns N worker SUBPROCESSES that fetch samples in")
    print("parallel, overlapping I/O with compute. On macOS/Windows workers use")
    print("the 'spawn' start method -> the Dataset + collate_fn are PICKLED to")
    print("each child (they must be top-level, importable, not lambdas). We")
    print("keep num_workers=0 here so output is byte-reproducible.\n")

    dl0 = DataLoader(ds, batch_size=4, num_workers=0)
    info = get_worker_info()
    print(f"{'get_worker_info() in main process':<40}{info}")
    print(f"{'dl.num_workers':<40}{dl0.num_workers}")
    print()

    dl_pin = DataLoader(ds, batch_size=4, num_workers=0, pin_memory=True)
    xb, _ = next(iter(dl_pin))
    print(f"{'dl with pin_memory=True':<40}{'(set)'}")
    print(f"{'xb.is_pinned() (no-op on CPU)':<40}{xb.is_pinned()}")
    print(f"{'str(xb.device)':<40}{str(xb.device)}")
    print()

    check("get_worker_info() is None in the main process", info is None)
    check("num_workers=0 means single-process loading", dl0.num_workers == 0)
    check("pin_memory is a no-op on CPU (tensor not pinned)",
          xb.is_pinned() is False)


# ----------------------------------------------------------------------------
# Section H — Transform callable applied inside __getitem__
# ----------------------------------------------------------------------------

def section_h_transform_pipeline() -> None:
    banner("H — A transform callable applied inside __getitem__")
    torch.manual_seed(0)
    ds = NormalizedDS()

    print("A transform is any callable applied to a sample. Applying it inside")
    print("__getitem__ means it runs per-sample (and, with num_workers>0, in a")
    print("worker process — for free). torchvision.transforms.Compose chains")
    print("several; the principle is identical.\n")

    raw = torch.arange(6, dtype=torch.float32).reshape(6, 1)
    print(f"{'raw x':<36}{raw.reshape(-1).tolist()}")
    print(f"{'mean':<36}{ds.mean.item():.6f}")
    print(f"{'std':<36}{ds.std.item():.6f}")
    print()
    sample0 = ds[0]
    print(f"{'ds[0] (normalized)':<36}{sample0.tolist()}")
    print(f"{'ds[1] (normalized)':<36}{ds[1].tolist()}")
    print()

    dl = DataLoader(ds, batch_size=3, shuffle=False)
    batch = next(iter(dl))
    print(f"{'batch shape':<36}{tuple(batch.shape)}")
    print(f"{'batch':<36}{batch.tolist()}")
    print()

    expected0 = ((raw[0] - ds.mean) / ds.std).item()
    all_norm = torch.stack([ds[i] for i in range(len(ds))])
    check("ds[0] == (raw[0] - mean) / std",
          abs(sample0.item() - expected0) < 1e-6)
    check("whole normalized dataset has mean ~0",
          abs(all_norm.mean().item()) < 1e-5)
    check("transform preserved shape: batch (3,1)", tuple(batch.shape) == (3, 1))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    torch.manual_seed(0)
    print("data_loading.py — Phase 5 bundle #32.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"torch {torch.__version__} on CPU.")
    section_a_map_style_dataset()
    section_b_dataloader_default_collate()
    section_c_custom_collate_fn()
    section_d_deterministic_shuffle()
    section_e_sampler()
    section_f_iterable_dataset()
    section_g_workers_and_pinning()
    section_h_transform_pipeline()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
