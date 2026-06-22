"""
nn_module.py — Bundle #31 (Phase 5).

GOAL (one line): show, by printing every value, that an nn.Module is the
composable unit of PyTorch — it holds Parameters (trainable) + buffers (not) +
sub-modules, builds a tree, and forward() runs via __call__ so hooks fire;
train()/eval() and .to() manage global state across the whole tree.

This is the GROUND TRUTH for NN_MODULE.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Deterministic: torch.manual_seed(0) before each model construction; CPU only.

Run:
    uv run python nn_module.py
"""

from __future__ import annotations

import torch
import torch.nn as nn

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
# Reference modules (defined at module level so __repr__ uses clean qualnames).
# ----------------------------------------------------------------------------

class MLP(nn.Module):
    """A tiny two-layer perceptron: Linear(4->8) -> ReLU -> Linear(8->1)."""

    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(4, 8)
        self.fc2 = nn.Linear(8, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(torch.relu(self.fc1(x)))


class ModelWithBuffer(nn.Module):
    """Linear with a non-trainable running-mean buffer subtracted first."""

    def __init__(self) -> None:
        super().__init__()
        self.register_buffer("mu", torch.zeros(4))
        self.fc = nn.Linear(4, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(x - self.mu)


# ----------------------------------------------------------------------------
# Section A — nn.Module subclass: Linear layers + a forward() pass
# ----------------------------------------------------------------------------

def section_a_subclass_and_forward() -> None:
    banner("A — nn.Module subclass: Linear layers + a forward() pass")
    torch.manual_seed(0)
    mlp = MLP()
    x = torch.arange(4, dtype=torch.float32)
    out = mlp(x)

    print("An nn.Module subclass holds its layers as attributes and defines")
    print("forward(). Instantiating the subclass builds the object; calling it")
    print("runs forward(). The base class is nn.Module itself.\n")

    print(f"{'isinstance(mlp, nn.Module)':<34}{isinstance(mlp, nn.Module)}")
    print(f"{'type(mlp).__name__':<34}{type(mlp).__name__!r}")
    print(f"{'type(mlp).__mro__':<34}{type(mlp).__mro__}")
    print(f"{'isinstance(mlp.fc1, nn.Linear)':<34}"
          f"{isinstance(mlp.fc1, nn.Linear)}")
    print("repr(mlp):")
    print(repr(mlp))
    print()
    print(f"{'x = torch.arange(4)':<34}{x.tolist()}")
    print(f"{'out = mlp(x)':<34}{out.tolist()}")
    print(f"{'tuple(out.shape)':<34}{tuple(out.shape)}")
    print()

    check("mlp is an nn.Module", isinstance(mlp, nn.Module))
    check("mlp's MRO is MLP -> Module -> object",
          type(mlp).__mro__ == (MLP, nn.Module, object))
    check("fc1 is an nn.Linear (a Module subclass)",
          isinstance(mlp.fc1, nn.Linear))
    check("mlp(x) output shape is (1,) for a (4,) input",
          tuple(out.shape) == (1,))


# ----------------------------------------------------------------------------
# Section B — Parameters auto-register: requires_grad=True
# ----------------------------------------------------------------------------

def section_b_parameters_auto_register() -> None:
    banner("B — Parameters auto-register: requires_grad=True")
    torch.manual_seed(0)
    mlp = MLP()

    print("nn.Linear's .weight and .bias are nn.Parameter objects (a Tensor")
    print("subclass). Assigning a Parameter as a Module attribute automatically")
    print("adds it to parameters(); assigning a plain Tensor does NOT.\n")

    print(f"{'type(mlp.fc1.weight).__name__':<40}"
          f"{type(mlp.fc1.weight).__name__!r}")
    print(f"{'isinstance(mlp.fc1.weight, nn.Parameter)':<40}"
          f"{isinstance(mlp.fc1.weight, nn.Parameter)}")
    print(f"{'mlp.fc1.weight.requires_grad':<40}"
          f"{mlp.fc1.weight.requires_grad}")
    print(f"{'mlp.fc1.bias.requires_grad':<40}{mlp.fc1.bias.requires_grad}")
    print(f"{'tuple(mlp.fc1.weight.shape)':<40}"
          f"{tuple(mlp.fc1.weight.shape)}")
    print(f"{'tuple(mlp.fc1.bias.shape)':<40}{tuple(mlp.fc1.bias.shape)}")
    print()

    n_params = sum(1 for _ in mlp.parameters())
    names = [name for name, _ in mlp.named_parameters()]
    print(f"{'len(list(mlp.parameters()))':<40}{n_params}")
    print(f"{'named_parameters() keys':<40}{names}")
    print()

    mlp.tmp = torch.zeros(3)  # a plain Tensor attribute -> NOT registered
    n_after = sum(1 for _ in mlp.parameters())
    print("mlp.tmp = torch.zeros(3)   # plain Tensor, not a Parameter\n")
    print(f"{'len(list(mlp.parameters())) after':<40}{n_after}")
    print(f"{'\"tmp\" in named_parameters()':<40}"
          f"{'tmp' in dict(mlp.named_parameters())}")
    print()

    check("fc1.weight is an nn.Parameter",
          isinstance(mlp.fc1.weight, nn.Parameter))
    check("fc1.weight.requires_grad is True",
          mlp.fc1.weight.requires_grad is True)
    check("fc1.bias.requires_grad is True", mlp.fc1.bias.requires_grad is True)
    check("fc1.weight has shape (8, 4) [out, in]",
          tuple(mlp.fc1.weight.shape) == (8, 4))
    check("parameters() has 4 tensors (2 layers x weight+bias)", n_params == 4)
    check("a plain Tensor attribute is NOT registered",
          n_after == 4 and "tmp" not in dict(mlp.named_parameters()))


# ----------------------------------------------------------------------------
# Section C — The sub-module tree: children / modules / named_modules
# ----------------------------------------------------------------------------

def section_c_submodule_tree() -> None:
    banner("C — The sub-module tree: children / modules / named_modules")
    torch.manual_seed(0)
    mlp = MLP()

    print("Assigning self.fc1 = nn.Linear(...) auto-registers fc1 as a CHILD")
    print("module. .children() yields direct children; .modules() yields self")
    print("plus all descendants; .named_modules() adds the dotted-path name.\n")

    child_names = [name for name, _ in mlp.named_children()]
    child_types = [type(m).__name__ for _, m in mlp.named_children()]
    mod_names = [name for name, _ in mlp.named_modules()]

    print(f"{'named_children() names':<32}{child_names}")
    print(f"{'children() types':<32}{child_types}")
    print(f"{'len(list(children()))':<32}{len(list(mlp.children()))}")
    print(f"{'named_modules() names':<32}{mod_names}")
    print(f"{'len(list(modules()))':<32}{len(list(mlp.modules()))}")
    print()

    check("MLP has 2 direct children (fc1, fc2)",
          len(list(mlp.children())) == 2)
    check("named_children() == ['fc1', 'fc2']", child_names == ["fc1", "fc2"])
    check("modules() includes self + 2 children = 3",
          len(list(mlp.modules())) == 3)
    check("named_modules() root key is '' (self)", mod_names[0] == "")


# ----------------------------------------------------------------------------
# Section D — state_dict(): the OrderedDict of params + persistent buffers
# ----------------------------------------------------------------------------

def section_d_state_dict() -> None:
    banner("D — state_dict(): params + persistent buffers keyed by path")
    torch.manual_seed(0)
    mlp = MLP()
    sd = mlp.state_dict()

    print("state_dict() returns a dict of all PARAMETERS + persistent BUFFERS,")
    print("keyed by dotted path. This is exactly what torch.save /")
    print("load_state_dict serialize. Values are detached (requires_grad off).\n")

    print(f"{'type(sd).__name__':<34}{type(sd).__name__!r}")
    print(f"{'isinstance(sd, dict)':<34}{isinstance(sd, dict)}")
    print(f"{'list(sd.keys())':<34}{list(sd.keys())}")
    print(f"{'len(sd)':<34}{len(sd)}")
    print(f"{'tuple(sd[\"fc1.weight\"].shape)':<34}"
          f"{tuple(sd['fc1.weight'].shape)}")
    print(f"{'sd[\"fc1.weight\"].requires_grad':<34}"
          f"{sd['fc1.weight'].requires_grad}")
    print()

    check("state_dict is a dict", isinstance(sd, dict))
    check("'fc1.weight' is a key", "fc1.weight" in sd)
    check("state_dict has 4 entries", len(sd) == 4)
    check("keys == ['fc1.weight','fc1.bias','fc2.weight','fc2.bias']",
          list(sd.keys()) == ["fc1.weight", "fc1.bias",
                              "fc2.weight", "fc2.bias"])
    check("state_dict values are detached (requires_grad False)",
          sd["fc1.weight"].requires_grad is False)


# ----------------------------------------------------------------------------
# Section E — forward() runs via __call__: hooks fire only through __call__
# ----------------------------------------------------------------------------

def section_e_call_vs_forward_hooks() -> None:
    banner("E — forward() runs via __call__: hooks fire only through __call__")
    torch.manual_seed(0)
    mlp = MLP()
    x = torch.arange(4, dtype=torch.float32)

    print("mlp(x) invokes Module.__call__, which runs forward hooks then")
    print("forward(). mlp.forward(x) calls forward() DIRECTLY and skips the")
    print("module's own hooks. Always use mlp(x), never mlp.forward(x).\n")

    records: list[torch.Tensor] = []

    def hook(_module: nn.Module, _args: tuple, out: torch.Tensor) -> None:
        records.append(out)

    handle = mlp.register_forward_hook(hook)
    out_call = mlp(x)            # __call__ -> hook fires
    out_direct = mlp.forward(x)  # direct   -> hook does NOT fire
    handle.remove()

    print(f"{'len(records) after mlp(x)':<42}{len(records)}")
    print(f"{'tuple(records[0].shape)':<42}{tuple(records[0].shape)}")
    print(f"{'len(records) after mlp.forward(x)':<42}{len(records)}")
    print(f"{'torch.equal(out_call, out_direct)':<42}"
          f"{torch.equal(out_call, out_direct)}")
    print()

    check("hook fired once on mlp(x) via __call__", len(records) == 1)
    check("hook recorded the (1,) output",
          tuple(records[0].shape) == (1,))
    check("mlp.forward(x) did NOT fire the hook again (still 1)",
          len(records) == 1)
    check("both call forms give identical output",
          torch.equal(out_call, out_direct))


# ----------------------------------------------------------------------------
# Section F — register_buffer: non-trainable tensors in the module state
# ----------------------------------------------------------------------------

def section_f_register_buffer() -> None:
    banner("F — register_buffer: non-trainable tensors in the module state")
    torch.manual_seed(0)
    m = ModelWithBuffer()

    print("register_buffer() stores a tensor that is part of the module's state")
    print("(so it is saved/moved with .to()) but is NOT a parameter (no grad).")
    print("BatchNorm's running_mean/running_var are the canonical example.\n")

    print(f"{'type(m.mu).__name__':<34}{type(m.mu).__name__!r}")
    print(f"{'isinstance(m.mu, nn.Parameter)':<34}"
          f"{isinstance(m.mu, nn.Parameter)}")
    print(f"{'m.mu.requires_grad':<34}{m.mu.requires_grad}")
    print(f"{'len(list(m.parameters()))':<34}{len(list(m.parameters()))}")
    print(f"{'named_buffers() names':<34}{[n for n, _ in m.named_buffers()]}")
    print(f"{'\"mu\" in m.state_dict()':<34}{'mu' in m.state_dict()}")
    print()

    check("the buffer is a Tensor, not a Parameter",
          isinstance(m.mu, torch.Tensor)
          and not isinstance(m.mu, nn.Parameter))
    check("buffer.requires_grad is False", m.mu.requires_grad is False)
    check("buffer is NOT in parameters() (only fc.weight, fc.bias = 2)",
          len(list(m.parameters())) == 2)
    check("buffer IS in state_dict()", "mu" in m.state_dict())


# ----------------------------------------------------------------------------
# Section G — train()/eval(): toggling self.training (Dropout/BatchNorm)
# ----------------------------------------------------------------------------

def section_g_train_eval() -> None:
    banner("G — train()/eval(): toggling self.training changes Dropout")
    torch.manual_seed(0)
    mlp = MLP()

    print("Every Module carries a `training` flag (True by default). train()/")
    print("eval() flip it recursively across the tree. Dropout multiplies/")
    print("zeroes in train mode but is the identity in eval mode — same")
    print("weights, different behavior.\n")

    default_flag = mlp.training
    mlp.eval()
    eval_flag = mlp.training
    mlp.train()
    train_flag = mlp.training
    print(f"{'mlp.training (default)':<38}{default_flag}")
    print(f"{'mlp.training after .eval()':<38}{eval_flag}")
    print(f"{'mlp.training after .train()':<38}{train_flag}")
    print()

    torch.manual_seed(0)
    drop = nn.Dropout(p=0.5)
    ones = torch.ones(2, 8)
    drop.train()
    out_train = drop(ones)
    drop.eval()
    out_eval = drop(ones)
    print("nn.Dropout(p=0.5) applied to ones(2, 8):")
    print(f"{'  train-mode output (some zeroed)':<38}{out_train.tolist()}")
    print(f"{'  eval-mode output (identity)':<38}{out_eval.tolist()}")
    print(f"{'(out_train == 0).any()':<38}{(out_train == 0).any().item()}")
    print(f"{'torch.equal(out_eval, ones)':<38}{torch.equal(out_eval, ones)}")
    print()

    check("default mlp.training is True", default_flag is True)
    check("eval() flips training to False", eval_flag is False)
    check("train() flips training back to True", train_flag is True)
    check("Dropout zeroes some entries in train mode",
          bool((out_train == 0).any()))
    check("Dropout is the identity in eval mode", torch.equal(out_eval, ones))


# ----------------------------------------------------------------------------
# Section H — .to(dtype) / .to(device): cast & move the whole tree
# ----------------------------------------------------------------------------

def section_h_to_device_and_dtype() -> None:
    banner("H — .to(dtype) / .to(device): cast & move the whole tree")
    torch.manual_seed(0)
    mlp = MLP()

    print(".to() moves/casts ALL parameters and buffers recursively, in place")
    print("(it returns self). .to(torch.float64) casts dtype; .to('cuda')/'mps'")
    print("moves device. Below: dtype cast (CPU, deterministic) + device report.\n")

    before = mlp.fc1.weight.dtype
    mlp.to(torch.float64)
    after = mlp.fc1.weight.dtype
    print(f"{'fc1.weight.dtype before .to(float64)':<44}{before}")
    print(f"{'fc1.weight.dtype after  .to(float64)':<44}{after}")
    print(f"{'fc2.bias.dtype after':<44}{mlp.fc2.bias.dtype}")
    print(f"{'str(fc1.weight.device)':<44}{str(mlp.fc1.weight.device)}")
    print(f"{'torch.cuda.is_available()':<44}{torch.cuda.is_available()}")
    print(f"{'torch.backends.mps.is_available()':<44}"
          f"{torch.backends.mps.is_available()}")
    print()

    check("default dtype is float32", before is torch.float32)
    check(".to(float64) cast fc1.weight", after is torch.float64)
    check("fc2.bias also cast to float64 (whole tree)",
          mlp.fc2.bias.dtype is torch.float64)
    check("params live on CPU by default",
          str(mlp.fc1.weight.device) == "cpu")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    torch.manual_seed(0)
    print("nn_module.py — Phase 5 bundle #31.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"torch {torch.__version__} on CPU.")
    section_a_subclass_and_forward()
    section_b_parameters_auto_register()
    section_c_submodule_tree()
    section_d_state_dict()
    section_e_call_vs_forward_hooks()
    section_f_register_buffer()
    section_g_train_eval()
    section_h_to_device_and_dtype()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
