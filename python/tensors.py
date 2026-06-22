"""
tensors.py — Phase 5 bundle (#29).

GOAL (one line): show, by printing every value, that a torch.Tensor is a typed,
device-resident, STRIDED n-d array whose `view`/`reshape`/`permute` ops share or
copy an underlying storage, whose elementwise ops are governed by broadcasting,
and whose in-place (`_` suffix) ops can break autograd.

This is the GROUND TRUTH for TENSORS.md. Every number, table, and worked example
in the guide is printed by this file. Change it -> re-run -> re-paste. Never
hand-compute.

Determinism: torch.manual_seed(0) before any RNG; every tensor lives on CPU
(universal + deterministic). cuda/mps are mentioned conceptually but never
required. Output is byte-reproducible on re-run.

Run:
    uv run python tensors.py
"""

from __future__ import annotations

import warnings

import numpy as np
import torch

# TypedStorage (tensor.storage()) is deprecated and prints a UserWarning; we use
# tensor.data_ptr() / untyped_storage() throughout, which are the stable APIs.
warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*")

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from the style anchor)
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
# Section A — creation, dtype, device
# ----------------------------------------------------------------------------

def section_a_creation_dtype_device() -> None:
    banner("A — Creation, dtype, device")
    print("A torch.Tensor is a multi-dimensional matrix of a SINGLE data type")
    print("(docs.pytorch.org tensors.html). torch.tensor(data) infers dtype from")
    print("the data; the factory ops (zeros/ones/arange/randn) use the DEFAULT")
    print("dtype = torch.float32. torch.get_default_dtype() confirms it.\n")

    torch.manual_seed(0)  # deterministic RNG for randn below
    from_list = torch.tensor([1, 2, 3])
    from_floats = torch.tensor([1.0, 2.0, 3.0])
    z = torch.zeros(2, 2)
    o = torch.ones(3)
    r = torch.arange(0, 12)
    n = torch.randn(2, 3)  # seeded -> byte-reproducible

    print(f"{'expression':<30}{'dtype':<16}{'shape'}")
    print("-" * 58)
    for label, t in [
        ("torch.tensor([1,2,3])", from_list),
        ("torch.tensor([1.,2.,3.])", from_floats),
        ("torch.zeros(2,2)", z),
        ("torch.ones(3)", o),
        ("torch.arange(0,12)", r),
        ("torch.randn(2,3) [seeded]", n),
    ]:
        print(f"{label:<30}{str(t.dtype):<16}{tuple(t.shape)}")
    print()
    print(f"torch.get_default_dtype() = {torch.get_default_dtype()}")
    print(f"every tensor above is on device: {n.device}")
    print(f"torch.backends.mps.is_available() = "
          f"{torch.backends.mps.is_available()}  (Apple Silicon GPU; conceptual)")
    print(f"seeded randn(2,3) values:\n{n}")
    print()

    check("torch.tensor([1,2,3]) infers int64 (integral data)",
          from_list.dtype is torch.int64)
    check("torch.tensor([1.,2.,3.]) infers float32 (default float dtype)",
          from_floats.dtype is torch.float32)
    check("torch.zeros uses the default dtype (float32)", z.dtype is torch.float32)
    check("default dtype is float32",
          torch.get_default_dtype() is torch.float32)
    check("CPU tensors report device type 'cpu'", str(n.device.type) == "cpu")
    check("torch.arange(0,12) has 12 elements", r.numel() == 12)


# ----------------------------------------------------------------------------
# Section B — dtype taxonomy, element_size, and .to()
# ----------------------------------------------------------------------------

def section_b_dtype_taxonomy() -> None:
    banner("B — dtype taxonomy, element_size(), and .to()")
    print("PyTorch's dtype fixes (a) the numeric kind and (b) the bytes/element.")
    print("element_size() returns bytes per element; nbytes = element_size() *")
    print("numel(). float32 is the DEFAULT and most accurate; float16/bfloat16")
    print("halve memory for training/inference; int64 is the index dtype.\n")

    samples = [
        ("torch.float32", torch.tensor(0.0)),
        ("torch.float16", torch.tensor(0.0, dtype=torch.float16)),
        ("torch.bfloat16", torch.tensor(0.0, dtype=torch.bfloat16)),
        ("torch.int64", torch.tensor(0, dtype=torch.int64)),
        ("torch.bool", torch.tensor(True)),
    ]
    print(f"{'dtype':<18}{'element_size (bytes)':<22}{'nbytes (10 elems)'}")
    print("-" * 60)
    for name, t in samples:
        ten = t.expand(10)  # 10-element view (shares storage)
        print(f"{name:<18}{t.element_size():<22}{ten.nbytes}")
    print()

    base = torch.tensor([1.5, -2.25, 3.0])      # float32
    cast = base.to(torch.float16)               # new tensor, half precision
    print(f"base.dtype = {base.dtype},  cast = base.to(torch.float16)")
    print(f"cast.dtype = {cast.dtype}")
    print(f"base.data_ptr() == cast.data_ptr() : "
          f"{base.data_ptr() == cast.data_ptr()}  (.to() to a new dtype COPIES)")
    print(f"cast values (note fp16 rounding of -2.25): {cast}")
    print()

    check("float32 element_size == 4 bytes",
          torch.tensor(0.0).element_size() == 4)
    check("float16 element_size == 2 bytes (half the memory)",
          torch.tensor(0.0, dtype=torch.float16).element_size() == 2)
    check("int64 element_size == 8 bytes (the index dtype)",
          torch.tensor(0, dtype=torch.int64).element_size() == 8)
    check("bool element_size == 1 byte",
          torch.tensor(True).element_size() == 1)
    check("nbytes == element_size() * numel()",
          torch.zeros(100).nbytes == 4 * 100)
    check(".to(new_dtype) produces a DISTINCT buffer (a copy)",
          base.data_ptr() != cast.data_ptr())


# ----------------------------------------------------------------------------
# Section C — view / reshape / permute / contiguous + shared storage
# ----------------------------------------------------------------------------

def section_c_view_reshape_permute() -> None:
    banner("C — view / reshape / permute / contiguous + shared storage")
    print("A tensor is a (dtype, shape, stride, storage-ptr) HEADER over a raw")
    print("1-D data buffer. view()/permute()/transpose() REWRITE the header and")
    print("SHARE the buffer (zero copy); reshape() shares when it can, COPIES")
    print("when it must; contiguous() materializes a row-major copy if needed.\n")

    a = torch.arange(12).reshape(2, 6)   # contiguous base
    print(f"a = torch.arange(12).reshape(2,6) =\n{a}")
    print(f"a.stride() = {a.stride()}  (row-jump=6, col-jump=1)\n")

    v = a.view(3, 4)                      # shares storage
    print(f"v = a.view(3,4) =\n{v}")
    print(f"a.data_ptr() == v.data_ptr() : {a.data_ptr() == v.data_ptr()}  "
          f"(view SHARES the buffer)")
    v[0, 0] = 999                         # mutate through the view
    print(f"v[0,0] = 999  ->  a[0,0] = {a[0, 0].item()}  (mutation visible in base)")
    print()

    # transpose -> a non-contiguous VIEW (strides flip, no data moved)
    t = a.transpose(0, 1)                 # shape (6,2), strides (1,6)
    print(f"t = a.transpose(0,1): shape={tuple(t.shape)} stride={t.stride()}")
    print(f"t.is_contiguous() = {t.is_contiguous()}")

    view_failed = False
    err_msg = ""
    try:
        t.view(2, 6)                      # would need to re-linearize -> ERROR
    except RuntimeError as exc:
        view_failed = True
        err_msg = str(exc).split("(")[0].strip()
    print(f"t.view(2,6) on non-contiguous t -> {'RuntimeError: ' + err_msg}")
    print()

    # .contiguous() materializes a row-major copy; then .view() works
    c = t.contiguous()
    print(f"c = t.contiguous(): is_contiguous={c.is_contiguous()} "
          f"stride={c.stride()}")
    print(f"c.data_ptr() == t.data_ptr() : {c.data_ptr() == t.data_ptr()}  "
          f"(contiguous COPIED non-contiguous data)")
    cv = c.view(2, 6)                     # now works
    print(f"c.view(2,6) after contiguous() -> shape {tuple(cv.shape)} (works)\n")

    # reshape() works on non-contiguous input (copies if it must)
    r = t.reshape(2, 6)
    print(f"r = t.reshape(2,6): shape={tuple(r.shape)}, "
          f"data_ptr == t: {r.data_ptr() == t.data_ptr()}  (reshape copied)")

    # contiguous() on an ALREADY-contiguous tensor returns ITSELF (no copy)
    self_view = a.contiguous()
    print(f"a.contiguous() returns same object when already contiguous: "
          f"{a is self_view}")

    # permute swaps axes (changes strides/header, never moves data)
    p = a.permute(1, 0)                   # == transpose for 2-D
    print(f"p = a.permute(1,0): shape={tuple(p.shape)} stride={p.stride()} "
          f"data_ptr == a: {p.data_ptr() == a.data_ptr()}")
    print()

    check("a.view(3,4) shares the buffer with a (same data_ptr)",
          a.data_ptr() == v.data_ptr())
    check("mutating a view is visible in the base (a[0,0] == 999)",
          a[0, 0].item() == 999)
    check("transpose() yields a non-contiguous view", not t.is_contiguous())
    check(".view() on a non-contiguous transpose raises RuntimeError",
          view_failed)
    check("contiguous() copies non-contiguous data (new data_ptr)",
          c.data_ptr() != t.data_ptr())
    check("reshape() succeeds on non-contiguous input (shape (2,6))",
          tuple(r.shape) == (2, 6))
    check("contiguous() on already-contiguous tensor returns the same object",
          a is self_view)
    check("permute(1,0) shares storage with the base (same data_ptr)",
          a.data_ptr() == p.data_ptr())


# ----------------------------------------------------------------------------
# Section D — strides & is_contiguous
# ----------------------------------------------------------------------------

def section_d_strides() -> None:
    banner("D — Strides & is_contiguous: the header that interprets the buffer")
    print("The k-th stride is the number of ELEMENTS to skip in the 1-D storage")
    print("to advance one step along axis k. A row-major (C-contiguous) tensor")
    print("has decreasing strides; a transposed view flips them. is_contiguous()")
    print("is True iff walking the axes in order visits storage in order.\n")

    base = torch.arange(12).reshape(3, 4)     # row-major: stride (4,1)
    print("base = torch.arange(12).reshape(3,4)")
    print(f"  shape={tuple(base.shape)}  stride={base.stride()}  "
          f"is_contiguous={base.is_contiguous()}")
    col = base.transpose(0, 1)                # column-major view: stride (1,4)
    print("col = base.transpose(0,1)")
    print(f"  shape={tuple(col.shape)}  stride={col.stride()}  "
          f"is_contiguous={col.is_contiguous()}")
    print(f"  col.data_ptr() == base.data_ptr() : "
          f"{col.data_ptr() == base.data_ptr()}  (SAME buffer, flipped strides)")
    print()
    print("Reading col[0,:] walks storage with step 4 -> the FIRST column of base.")
    print(f"  base[:, 0] = {base[:, 0].tolist()}")
    print(f"  col[0, :]  = {col[0, :].tolist()}   (identical: same bytes, new map)")
    print()

    check("a (3,4) row-major tensor has stride (4,1)",
          base.stride() == (4, 1))
    check("transpose flips the strides to (1,4)",
          col.stride() == (1, 4))
    check("base is contiguous, its transpose is NOT",
          base.is_contiguous() and not col.is_contiguous())
    check("transpose shares the buffer (same data_ptr)",
          col.data_ptr() == base.data_ptr())
    check("col[0,:] equals base[:,0] (same bytes, reinterpreted)",
          torch.equal(col[0, :], base[:, 0]))


# ----------------------------------------------------------------------------
# Section E — broadcasting
# ----------------------------------------------------------------------------

def section_e_broadcasting() -> None:
    banner("E — Broadcasting: align TRAILING dims; each must be equal or 1")
    print("Two shapes are broadcastable iff, iterating from the TRAILING dim, each")
    print("pair is equal OR one of them is 1 (or absent). The result dim is the")
    print("max. Broadcasting expands WITHOUT copying (a stride-0 trick).\n")

    matrix = torch.arange(12).reshape(3, 4).float()
    row_vec = torch.tensor([10.0, 20.0, 30.0, 40.0])        # shape (4,)
    col_vec = torch.tensor([[100.0], [200.0], [300.0]])     # shape (3,1)
    one_row = torch.tensor([1.0, 2.0, 3.0, 4.0]).reshape(1, 4)  # shape (1,4)

    sum_mr = matrix + row_vec
    outer = col_vec * one_row

    print(f"matrix  shape {tuple(matrix.shape)}")
    print(f"row_vec shape {tuple(row_vec.shape)}  -> matrix + row_vec "
          f"shape {tuple(sum_mr.shape)}")
    print(f"col_vec shape {tuple(col_vec.shape)} ; one_row shape {tuple(one_row.shape)}"
          f" -> col_vec * one_row shape {tuple(outer.shape)}")
    print()
    print(f"matrix + row_vec (row broadcast across 3 rows):\n{sum_mr}")
    print(f"\ncol_vec * one_row (outer product via broadcasting):\n{outer}")
    print()

    not_broadcastable = False
    err_msg = ""
    bad = torch.arange(6).reshape(2, 3).float()
    try:
        bad + torch.arange(4).reshape(2, 2)  # trailing dims 3 vs 2 -> error
    except RuntimeError as exc:
        not_broadcastable = True
        err_msg = str(exc).split("\n")[0][:70]
    print(f"(2,3) + (2,2) -> {'RuntimeError: ' + err_msg}  (3 != 2)")
    print()

    check("(3,4) + (4,) broadcasts the row to (3,4)",
          tuple(sum_mr.shape) == (3, 4))
    check("(3,1) * (1,4) broadcasts to (3,4) (outer product)",
          tuple(outer.shape) == (3, 4))
    check("matrix + row_vec adds the SAME row to every row",
          torch.equal(sum_mr[0], matrix[0] + row_vec)
          and torch.equal(sum_mr[1], matrix[1] + row_vec))
    check("(2,3) + (2,2) is NOT broadcastable (trailing 3 != 2)",
          not_broadcastable)
    check("broadcasting result dim = max of the two along each axis",
          tuple(outer.shape) == (max(3, 1), max(1, 4)))


# ----------------------------------------------------------------------------
# Section F — in-place ops, the `_` suffix, and the autograd trap
# ----------------------------------------------------------------------------

def section_f_inplace() -> None:
    banner("F — In-place ops: the `_` suffix and the autograd trap")
    print("A method ending in `_` (add_, relu_, abs_, zero_) mutates the tensor")
    print("in place and returns it — no new buffer. Fast, but DANGEROUS under")
    print("autograd: an in-place op on a LEAF tensor that requires grad raises")
    print("immediately. (🔗 AUTOCRAD, Phase 5 #30, covers the full graph theory.)\n")

    t = torch.tensor([-1.0, 2.0, -3.0])
    t_ptr_before = t.data_ptr()               # capture buffer address (stable)
    print(f"t = {t.tolist()}")
    ret = t.relu_()                           # in-place ReLU
    print(f"t.relu_() -> t = {t.tolist()}  (mutated in place)")
    print(f"data_ptr(t) unchanged: {t.data_ptr() == t_ptr_before}  "
          f"ret is t: {ret is t}  (same object, same buffer)\n")

    out_of_place = torch.tensor([-1.0, 2.0, -3.0]).relu()
    print(f"torch.tensor([...]).relu() (OUT-of-place) -> {out_of_place.tolist()}")
    print("(the `_`-less form returns a NEW tensor; original untouched)\n")

    leaf_error = False
    err_msg = ""
    leaf = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    try:
        leaf.add_(1.0)                       # in-place on a grad leaf -> ERROR
    except RuntimeError as exc:
        leaf_error = True
        err_msg = str(exc).split("\n")[0][:75]
    print(f"leaf.add_(1) on a requires_grad=True leaf -> "
          f"{'RuntimeError: ' + err_msg}")
    print()

    check("relu_() mutates in place (t == [0,2,0])",
          t.tolist() == [0.0, 2.0, 0.0])
    check("the in-place method returns the SAME object (ret is t)", ret is t)
    check("the out-of-place relu() does NOT mutate its source",
          out_of_place.tolist() == [0.0, 2.0, 0.0])
    check("in-place on a requires_grad leaf raises RuntimeError", leaf_error)


# ----------------------------------------------------------------------------
# Section G — indexing: slice (view), boolean mask, advanced (copy)
# ----------------------------------------------------------------------------

def section_g_indexing() -> None:
    banner("G — Indexing: slice (view) vs boolean mask vs advanced (copy)")
    print("PyTorch follows NumPy: BASIC indexing (slices/int) returns a VIEW of")
    print("the base; BOOLEAN MASK and ADVANCED indexing (tensor/idx arrays) return")
    print("a COPY. Writing through either kind is always in-place.\n")

    t = torch.arange(12).reshape(3, 4)
    print(f"t =\n{t}")

    row0 = t[0, :]                           # basic -> view
    mask = t > 5                             # boolean mask
    picked = t[mask]                         # advanced -> copy
    idx = torch.tensor([0, 2, 2])
    gathered = t[idx, :]                     # advanced -> copy

    print(f"\nt[0, :]   (basic slice)    -> {row0.tolist()}")
    print(f"  is view of t: {row0.data_ptr() == t.data_ptr()}")
    print(f"(t > 5)   (boolean mask)    -> shape {tuple(mask.shape)}, "
          f"{int(mask.sum())} True entries")
    print(f"t[t>5]    (advanced, mask)  -> {picked.tolist()}  (1-D copy)")
    print(f"t[[0,2,2],:]  (advanced idx) -> shape {tuple(gathered.shape)} "
          f"(rows 0,2,2 gathered)\n")

    row0[0] = -7                             # mutate the VIEW -> leaks into t
    print(f"row0[0] = -7 (mutate the slice view) -> t[0,0] = {t[0, 0].item()}")
    print()

    check("basic slice t[0,:] shares storage with t (a view)",
          row0.data_ptr() == t.data_ptr())
    check("boolean mask t[t>5] returns a 1-D copy of the matches",
          picked.tolist() == [6, 7, 8, 9, 10, 11])
    check("advanced indexing t[[0,2,2],:] gathers rows (0,2,2)",
          gathered.shape == (3, 4) and gathered[1].tolist() == t[2].tolist())
    check("mutating a slice view mutates the base (t[0,0] == -7)",
          t[0, 0].item() == -7)
    check("the mask dtype is bool", mask.dtype is torch.bool)


# ----------------------------------------------------------------------------
# Section H — NumPy interop: zero-copy on CPU
# ----------------------------------------------------------------------------

def section_h_numpy_interop() -> None:
    banner("H — NumPy interop: t.numpy() and torch.from_numpy() share memory")
    print("On CPU, a torch.Tensor and the ndarray from t.numpy() share the SAME")
    print("raw buffer (zero copy). torch.from_numpy(arr) wraps an ndarray as a")
    print("tensor the same way. Mutating either is visible to the other.\n")

    t = torch.tensor([1.0, 2.0, 3.0, 4.0])
    arr = t.numpy()                          # shares memory with t
    print("t = torch.tensor([1.,2.,3.,4.])")
    print(f"arr = t.numpy()  -> type={type(arr).__name__}, "
          f"dtype={arr.dtype}, values={arr.tolist()}")
    print(f"t.data_ptr() == arr.__array_interface__['data'][0] : "
          f"{t.data_ptr() == arr.__array_interface__['data'][0]}  (shared buffer)")

    arr[0] = 99.0                            # mutate the numpy side
    print(f"\narr[0] = 99.0  ->  t = {t.tolist()}  (torch sees the numpy mutation)")
    t[1] = -42.0                             # mutate the torch side
    print(f"t[1] = -42.0  ->  arr = {arr.tolist()}  (numpy sees the torch mutation)")

    back = torch.from_numpy(arr)             # wrap ndarray back into a tensor
    print(f"\nback = torch.from_numpy(arr) -> shares buffer: "
          f"{back.data_ptr() == t.data_ptr()}")
    print("(from_numpy PRESERVES dtype: float32 ndarray -> float32 tensor,")
    print(" NOT the float32 'default' rule that torch.tensor() uses.)")

    # The dtype-preservation contrast: a numpy float64 array maps to float64.
    f64_arr = np.array([1.0, 2.0], dtype=np.float64)
    f64_t = torch.from_numpy(f64_arr)
    print(f"np.array([1.,2.], dtype=float64) -> from_numpy -> dtype "
          f"{f64_t.dtype} (preserved, NOT float32)")
    print()

    check("t.numpy() returns a numpy.ndarray", isinstance(arr, np.ndarray))
    check("t.numpy() shares the buffer with t (same data pointer)",
          t.data_ptr() == arr.__array_interface__['data'][0])
    check("mutating the ndarray is visible in the tensor (t[0] == 99.0)",
          t[0].item() == 99.0)
    check("mutating the tensor is visible in the ndarray (arr[1] == -42.0)",
          arr[1] == -42.0)
    check("torch.from_numpy(arr) shares the buffer too",
          back.data_ptr() == t.data_ptr())
    check("from_numpy PRESERVES dtype (float64 ndarray -> torch.float64)",
          f64_t.dtype is torch.float64)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print(f"tensors.py — Phase 5 bundle #29.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. All tensors live on CPU for\n"
          "determinism; cuda/mps are mentioned only conceptually.\n"
          f"torch {torch.__version__}, numpy {np.__version__} on this machine.")
    section_a_creation_dtype_device()
    section_b_dtype_taxonomy()
    section_c_view_reshape_permute()
    section_d_strides()
    section_e_broadcasting()
    section_f_inplace()
    section_g_indexing()
    section_h_numpy_interop()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
