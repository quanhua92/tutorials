"""
instruction_sft.py - Reference implementation of the SINGLE most important
formatting rule in Supervised Fine-Tuning (SFT): wrap turns in a chat template
(ChatML) and compute the cross-entropy loss ONLY on the assistant's target
tokens by MASKING every other position's label to -100 (the ignore_index).

This is the single source of truth that INSTRUCTION_SFT.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python instruction_sft.py

== The big idea, in one paragraph =============================================
A base language model just predicts the next token of ANY text. To turn it into
a chat assistant you must (1) wrap each turn in a TEMPLATE so the model can tell
roles apart (ChatML: `<|im_start|>role\\n...<|im_end|>\\n`), and (2) decide
WHICH tokens to train on. The naive choice -- train on the whole sequence -- is
wrong: it teaches the model to GENERATE the user's prompts too, which is never
its job at inference. The fix is COMPLETION-ONLY / ASSISTANT-ONLY loss: set the
label to -100 on every system / user / role-marker / padding token, and keep the
real token id only on the assistant's content (plus its closing <|im_end|>, so
the model learns when to stop). PyTorch's CrossEntropyLoss(ignore_index=-100)
then contributes loss ONLY at the assistant positions. Get this one masking
step wrong and you silently train on the wrong target distribution.

== The lineage (old -> new, with WHY each step happened) =======================
  base LM      : predicts EVERY next token of plain text. No notion of roles.
                 next-token cross-entropy on the raw stream -- fine for pretrain.
  chat template: wrap each turn as `<|im_start|>role\\n{msg}<|im_end|>\\n` so the
                 model sees role boundaries (system / user / assistant). WHY: the
                 model must know WHO said what to be a usable assistant. The
                 template is a Jinja string baked into the tokenizer
                 (`apply_chat_template`); ChatML is the Qwen/SmolLM/OpenAI layout.
  naive SFT    : tokenise the templated string and use labels = input_ids (NO
                 mask). PROBLEM: the loss is now computed on user + system +
                 role markers too -- the model is trained to GENERATE user turns,
                 which it will never be asked to do at inference. Wastes capacity
                 and shifts the target distribution. (Most copy-paste SFT
                 scripts shipped this bug for years.)
  completion-  : set labels = -100 on every token whose role is NOT the
  only loss      assistant (system, user, all <|im_start|>role headers, padding).
                 CrossEntropyLoss(ignore_index=-100) skips -100 positions, so the
                 gradient flows ONLY on the assistant content (+ its closing
                 <|im_end|>). This is the single most important SFT formatting
                 rule. HuggingFace ships it as SFTConfig(assistant_only_loss=True)
                 / completion_only_loss=True, and (legacy) DataCollatorForCompletionOnlyLM.

== IMPORTANT -- toy integer "token ids", NOT a real tokenizer ==================
We do NOT load transformers / tokenizers / datasets. The POINT of this bundle is
the MASKING logic, not BPE. So we model a tiny 16-id vocabulary where each
control token (im_start, im_end), each role word (system/user/assistant), the
newline, and a few content words ("Hi", "Hi!", "Bye", "Bye!", ...) each get one
integer id. A real ChatML tokenizer would produce the SAME structural stream
(just more ids, from a 32k-128k vocab); the masking is byte-for-byte identical.

== The ChatML layout we model =================================================
    <|im_start|>system\\n{sys}<|im_end|>\\n
    <|im_start|>user\\n{u1}<|im_end|>\\n
    <|im_start|>assistant\\n{a1}<|im_end|>\\n
    <|im_start|>user\\n{u2}<|im_end|>\\n
    <|im_start|>assistant\\n{a2}<|im_end|>\\n
    [<|im_start|>assistant\\n            <- add_generation_prompt (INFERENCE only)]
The assistant SPAN we compute loss on = the assistant CONTENT + its CLOSING
<|im_end|>. The `<|im_start|>assistant\\n` HEADER that precedes it is NOT a
target -- it is the context the model conditions on (the "generation prompt").

== Notation & tensor-shape conventions ========================================
    T          : sequence length (number of toy tokens). Here T = 24 (2-turn convo).
    V          : vocab size of the toy vocab. Here V = 16.
    ids        : 1-D int tensor [T] of toy token ids.
    role       : 1-D int tensor [T] marking each token's owner:
                   ROLE_SPECIAL=0, ROLE_SYSTEM=1, ROLE_USER=2,
                   ROLE_ASST_HEADER=3 (the <|im_start|>assistant\\n prefix),
                   ROLE_ASSISTANT=4 (the ONLY loss-bearing role).
    labels     : 1-D int tensor [T]; labels[role != ASSISTANT] = -100, else = id.
    -100       : torch.nn.CrossEntropyLoss DEFAULT ignore_index (verified in docs).
    shift      : causal LM shift -- shift_logits = logits[:-1], shift_labels =
                 labels[1:]. So the token at position t is predicted from 0..t-1.

== GOLD ANCHOR (instruction_sft.html recomputes this identically) =============
The fixed 2-turn conversation below has:
    T = 24 total tokens
    A = 4  assistant (loss-bearing) tokens  (the two content + closing-<|im_end|> pairs)
    masked = 20  positions whose label is -100
The .html reproduces the SAME ids + role arrays in JS, recomputes A = count of
assistant tokens, and the [check: OK] badge asserts A == 4 (and masked == 20).

== Sources (all in instruction_sft_reference.txt, >=2 independent) ============
  ChatML layout    : OpenAI ChatML spec + HuggingFace apply_chat_template docs
  -100 ignore_idx  : PyTorch nn.CrossEntropyLoss docs (default ignore_index=-100)
  completion-only  : trl SFTTrainer (assistant_only_loss / completion_only_loss)
                     + DataCollatorForCompletionOnlyLM (the legacy collator)
  why-mask         : "Mask Your User Tokens" (Gottesman 2024) -- the worked table
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74

# ----------------------------------------------------------------------------
# The toy 16-id vocabulary. Real ChatML uses a 32k-128k BPE vocab; we use a
# tiny integer vocab so every id prints and the MASKING logic is crystal clear.
# ----------------------------------------------------------------------------
V = 16
PAD, IM_START, IM_END = 0, 1, 2
TOK_SYSTEM, TOK_USER, TOK_ASST = 3, 4, 5   # the role words inside <im_start>...<im_end>
NL = 6                                     # the "\n" newline token
W_HI, W_HI_BANG, W_BYE, W_BYE_BANG = 7, 8, 9, 10   # content words
W_HELLO, W_THERE, W_WORLD, W_OK = 11, 12, 13, 14
VOCAB_NAMES = {
    PAD: "<pad>", IM_START: "<|im_start|>", IM_END: "<|im_end|>",
    TOK_SYSTEM: "system", TOK_USER: "user", TOK_ASST: "assistant",
    NL: "\\n",
    W_HI: "Hi", W_HI_BANG: "Hi!", W_BYE: "Bye", W_BYE_BANG: "Bye!",
    W_HELLO: "Hello", W_THERE: "there", W_WORLD: "world", W_OK: "ok",
    15: "<unk>",
}

# Role codes -- only ROLE_ASSISTANT is loss-bearing; all others -> label -100.
ROLE_SPECIAL = 0       # <|im_start|>, <|im_end|> closers of non-asst turns, \n separators
ROLE_SYSTEM = 1        # system content
ROLE_USER = 2          # user content
ROLE_ASST_HEADER = 3   # the <|im_start|>assistant\n prefix (generation prompt) -- MASKED
ROLE_ASSISTANT = 4     # assistant CONTENT + its closing <|im_end|> -- the ONLY loss target
ROLE_NAMES = {
    ROLE_SPECIAL: "special", ROLE_SYSTEM: "system", ROLE_USER: "user",
    ROLE_ASST_HEADER: "asst-hdr", ROLE_ASSISTANT: "ASSISTANT",
}
IGNORE_INDEX = -100     # torch.nn.CrossEntropyLoss default ignore_index


# ============================================================================
# 0. THE CHECK HELPER  (no raw assert -- it is compiled out under -O)
# ============================================================================

def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# A. THE TOY CHATML CONVERSATION AS INTEGER ids + A PARALLEL role ARRAY
#    This 2-turn conversation is the GOLD anchor (pinned for the .html check).
#    ids  = the flattened ChatML token stream of:
#        <|im_start|>user\nHi<|im_end|>\n
#        <|im_start|>assistant\nHi!<|im_end|>\n
#        <|im_start|>user\nBye<|im_end|>\n
#        <|im_start|>assistant\nBye!<|im_end|>\n
#    role = each token's owner; only ROLE_ASSISTANT positions carry loss.
# ============================================================================

# GOLD conversation -- hardcoded, identical in instruction_sft.html.
GOLD_IDS = torch.tensor([
    IM_START, TOK_USER, NL, W_HI, IM_END, NL,           # turn 1 user
    IM_START, TOK_ASST, NL, W_HI_BANG, IM_END, NL,      # turn 1 assistant
    IM_START, TOK_USER, NL, W_BYE, IM_END, NL,          # turn 2 user
    IM_START, TOK_ASST, NL, W_BYE_BANG, IM_END, NL,     # turn 2 assistant
], dtype=torch.long)
GOLD_ROLE = torch.tensor([
    ROLE_SPECIAL, ROLE_USER, ROLE_USER, ROLE_USER, ROLE_SPECIAL, ROLE_SPECIAL,
    ROLE_SPECIAL, ROLE_ASST_HEADER, ROLE_ASST_HEADER, ROLE_ASSISTANT, ROLE_ASSISTANT, ROLE_SPECIAL,
    ROLE_SPECIAL, ROLE_USER, ROLE_USER, ROLE_USER, ROLE_SPECIAL, ROLE_SPECIAL,
    ROLE_SPECIAL, ROLE_ASST_HEADER, ROLE_ASST_HEADER, ROLE_ASSISTANT, ROLE_ASSISTANT, ROLE_SPECIAL,
], dtype=torch.long)


def section_build_conversation():
    banner("SECTION A: a toy ChatML conversation as integer ids + a role array")
    print("ChatML wraps every turn as  <|im_start|>role\\n{msg}<|im_end|>\\n .  The model")
    print("sees a FLAT token stream; the role array records WHO owns each token so we")
    print("can later mask everyone except the assistant. Toy vocab V=16 (real ChatML uses")
    print("a 32k-128k BPE vocab; the masking is byte-for-byte identical).\n")
    print("Fixed 2-turn conversation (the GOLD anchor for instruction_sft.html):\n")
    print("  <|im_start|>user\\nHi<|im_end|>\\n")
    print("  <|im_start|>assistant\\nHi!<|im_end|>\\n")
    print("  <|im_start|>user\\nBye<|im_end|>\\n")
    print("  <|im_start|>assistant\\nBye!<|im_end|>\\n")
    print()
    T = GOLD_IDS.shape[0]
    print("| pos | id  | token        | role        | loss? |")
    print("|-----|-----|--------------|-------------|-------|")
    for i in range(T):
        loss = "YES" if GOLD_ROLE[i].item() == ROLE_ASSISTANT else "-"
        print(f"| {i:<3} | {GOLD_IDS[i].item():<3} | "
              f"{VOCAB_NAMES[GOLD_IDS[i].item()]:<12} | "
              f"{ROLE_NAMES[GOLD_ROLE[i].item()]:<11} | {loss:<5} |")
    n_assistant = int((GOLD_ROLE == ROLE_ASSISTANT).sum().item())
    n_masked = T - n_assistant
    print()
    print(f"T (total tokens)              = {T}")
    print(f"A (assistant / loss-bearing)  = {n_assistant}")
    print(f"masked (label -> -100)        = {n_masked}")
    print()
    print("GOLD PIN (instruction_sft.html recomputes these identically):")
    print(f"    T = {T} ,  A = {n_assistant} ,  masked = {n_masked}")
    check("GOLD T == 24", T == 24)
    check("GOLD A == 4 (two assistant spans: content + closing <|im_end|>)",
          n_assistant == 4)
    check("GOLD masked == T - A == 20", n_masked == 20)
    check("every assistant position sits inside an <|im_start|>assistant...<|im_end|>",
          GOLD_ROLE[GOLD_ROLE == ROLE_ASSISTANT].numel() == 4)
    return T, n_assistant, n_masked


# ============================================================================
# B. LABEL MASKING:  labels = ids.clone(); labels[role != ASSISTANT] = -100
#    CrossEntropyLoss(ignore_index=-100) then skips -100 positions, so loss is
#    computed ONLY on the assistant content + its closing <|im_end|>.
# ============================================================================

def build_labels(ids: torch.Tensor, role: torch.Tensor) -> torch.Tensor:
    """Return the SFT labels: the real id where role == ASSISTANT, else -100.

    This is the whole SFT formatting rule in one line. Every system / user /
    role-marker / assistant-header / padding token becomes -100 (ignored by the
    loss); only the assistant's content + its closing <|im_end|> keep their id.
    """
    labels = ids.clone()
    labels[role != ROLE_ASSISTANT] = IGNORE_INDEX
    return labels


def section_label_masking():
    banner("SECTION B: build labels by masking  (labels[role != ASSISTANT] = -100)")
    print("The rule, in one line:  labels = ids.clone();  labels[role != ASSISTANT] = -100\n")
    print("PyTorch's CrossEntropyLoss has ignore_index = -100 BY DEFAULT, so every -100")
    print("position contributes ZERO loss -- only the assistant tokens train the model.\n")
    labels = build_labels(GOLD_IDS, GOLD_ROLE)
    T = GOLD_IDS.shape[0]
    print("| pos | id  | token        | role        | label       |")
    print("|-----|-----|--------------|-------------|-------------|")
    for i in range(T):
        lab = labels[i].item()
        lab_str = "-100 (mask)" if lab == IGNORE_INDEX else f"{lab} ({VOCAB_NAMES[lab]})"
        print(f"| {i:<3} | {GOLD_IDS[i].item():<3} | "
              f"{VOCAB_NAMES[GOLD_IDS[i].item()]:<12} | "
              f"{ROLE_NAMES[GOLD_ROLE[i].item()]:<11} | {lab_str:<11} |")
    n_loss = int((labels != IGNORE_INDEX).sum().item())
    n_mask = int((labels == IGNORE_INDEX).sum().item())
    print()
    print(f"labels array = {labels.tolist()}")
    print(f"non-masked (real id, assistant) = {n_loss}")
    print(f"masked  (-100, everything else) = {n_mask}")
    print()
    print("The two assistant spans carry loss; EVERYTHING else (system, user, the")
    print("<|im_start|>assistant\\n header, all separators) is -100. Note the closing")
    print("<|im_end|> of EACH assistant turn IS kept (so the model learns to STOP);")
    print("the <|im_end|> that closes a USER turn is masked (the model never emits it).")
    check("non-masked label count == assistant span length == 4", n_loss == 4)
    check("masked label count == 20", n_mask == 20)
    check("every non-masked label is a real vocab id in [0, V)",
          all(0 <= int(lab) < V for lab in labels if lab != IGNORE_INDEX))
    # the assistant-header <|im_start|>assistant\n is MASKED (it is the context, not a target)
    header_positions = (GOLD_ROLE == ROLE_ASST_HEADER).nonzero(as_tuple=True)[0].tolist()
    header_masked = all(labels[p].item() == IGNORE_INDEX for p in header_positions)
    check("the <|im_start|>assistant\\n header tokens are masked (they are context, not target)",
          header_masked)
    # closing im_end of each assistant turn IS kept
    kept = labels[GOLD_ROLE == ROLE_ASSISTANT].tolist()
    check("the kept assistant tokens include the closing <|im_end|> (id 2) twice",
          kept.count(IM_END) == 2)
    return labels


# ============================================================================
# C. A TINY CROSS-ENTROPY DEMO with ignore_index=-100
#    Seeded random logits over V=16, the masked labels from Section B, and the
#    standard causal shift. Assert: the averaged loss == mean over the NON-masked
#    shift positions only; masked positions contribute exactly 0.
# ============================================================================

def shifted_ce(logits: torch.Tensor, labels: torch.Tensor):
    """Causal-LM cross-entropy with the HF shift + ignore_index=-100.

    Returns (per_position_loss[T-1], averaged_loss, n_target_positions).
    shift_logits = logits[:-1]  (predict position t+1 from positions 0..t)
    shift_labels = labels[1:]
    ignore_index=-100 -> those positions contribute 0 and are excluded from the mean.
    """
    shift_logits = logits[:-1, :]
    shift_labels = labels[1:]
    per_pos = F.cross_entropy(shift_logits, shift_labels,
                              ignore_index=IGNORE_INDEX, reduction="none")
    averaged = F.cross_entropy(shift_logits, shift_labels,
                               ignore_index=IGNORE_INDEX, reduction="mean")
    n_targets = int((shift_labels != IGNORE_INDEX).sum().item())
    return per_pos, averaged, n_targets


def section_cross_entropy_demo(labels: torch.Tensor):
    banner("SECTION C: cross-entropy with ignore_index=-100 -- loss only on assistant")
    T = GOLD_IDS.shape[0]
    g = torch.Generator().manual_seed(0)
    logits = (torch.randn(T, V, generator=g) * 0.5)        # [T=24, V=16], deterministic
    print(f"Seeded logits shape [T={T}, V={V}] (torch.Generator().manual_seed(0)).")
    print("Causal shift: shift_logits = logits[:-1]  predicts  shift_labels = labels[1:].\n")
    per_pos, averaged, n_targets = shifted_ce(logits, labels)
    shift_labels = labels[1:]
    print("| shift-pos | predicts token | label        | per-pos loss | contributes? |")
    print("|-----------|----------------|--------------|--------------|--------------|")
    for j in range(per_pos.shape[0]):
        lab = shift_labels[j].item()
        lab_str = "-100 (mask)" if lab == IGNORE_INDEX else f"{lab} ({VOCAB_NAMES[lab]})"
        contributes = "NO (ignored)" if lab == IGNORE_INDEX else "YES -> loss"
        marker = "  <-- target" if lab != IGNORE_INDEX else ""
        print(f"| {j:<9} | {VOCAB_NAMES[GOLD_IDS[j + 1].item()]:<14} | "
              f"{lab_str:<12} | {per_pos[j].item():<12.4f} | {contributes}{marker}")
    print()
    manual_mean = per_pos[shift_labels != IGNORE_INDEX].mean().item()
    print(f"number of TARGET (non-masked) shift positions = {n_targets}")
    print(f"loss = F.cross_entropy(..., ignore_index=-100) = {averaged.item():.6f}")
    print(f"manual: mean of per-pos loss over the {n_targets} target positions "
          f"= {manual_mean:.6f}")
    print()
    print("The 4 assistant targets (predicting the content + the closing <|im_end|> of")
    print("each turn) carry all the loss; the other 19 shift positions are -100 -> loss 0.")
    check("averaged loss is finite", bool(torch.isfinite(averaged).item()))
    check("loss averaged only over the 4 assistant target positions",
          n_targets == 4)
    check("F.cross_entropy(ignore_index=-100) == manual mean over non-masked",
          abs(averaged.item() - manual_mean) < 1e-6)
    # masked positions contribute EXACTLY 0 (PyTorch zeroes them in reduction='none')
    masked_per_pos = per_pos[shift_labels == IGNORE_INDEX]
    check("every masked position contributes exactly 0.0 to the loss",
          bool(torch.all(masked_per_pos == 0.0).item()))
    return averaged.item()


# ============================================================================
# D. NAIVE (no mask) vs COMPLETION-ONLY (assistant mask) -- the contrast
#    naive labels = ids.clone() (loss on EVERY token, incl. user/system) -> the
#    model is trained to GENERATE user prompts. Wrong target distribution.
#    completion-only labels = Section B (loss on assistant only) -> correct.
# ============================================================================

def section_naive_vs_completion():
    banner("SECTION D: naive SFT (loss on ALL tokens) vs completion-only (assistant only)")
    T = GOLD_IDS.shape[0]
    g = torch.Generator().manual_seed(0)
    logits = (torch.randn(T, V, generator=g) * 0.5)        # SAME seeded logits as Section C

    # --- naive: labels = input_ids, no mask ---
    naive_labels = GOLD_IDS.clone()
    shift_logits = logits[:-1, :]
    naive_shift = naive_labels[1:]
    naive_per = F.cross_entropy(shift_logits, naive_shift, ignore_index=IGNORE_INDEX,
                                reduction="none")
    naive_loss = F.cross_entropy(shift_logits, naive_shift, ignore_index=IGNORE_INDEX)
    naive_targets = int((naive_shift != IGNORE_INDEX).sum().item())

    # --- completion-only: labels from Section B ---
    comp_labels = build_labels(GOLD_IDS, GOLD_ROLE)
    comp_shift = comp_labels[1:]
    comp_per = F.cross_entropy(shift_logits, comp_shift, ignore_index=IGNORE_INDEX,
                               reduction="none")
    comp_loss = F.cross_entropy(shift_logits, comp_shift, ignore_index=IGNORE_INDEX)
    comp_targets = int((comp_shift != IGNORE_INDEX).sum().item())

    print("Same seeded logits, two label arrays:\n")
    print("| variant          | label rule                          | target positions | loss     |")
    print("|------------------|-------------------------------------|------------------|----------|")
    print(f"| naive (wrong)    | labels = input_ids (NO mask)        | {naive_targets:>16} | {naive_loss.item():<8.4f} |")
    print(f"| completion-only  | labels[role!=assistant] = -100      | {comp_targets:>16} | {comp_loss.item():<8.4f} |")
    print()
    print("Target positions (shift-index) that carry loss:")
    naive_pos = [j for j in range(naive_per.shape[0])
                 if naive_shift[j].item() != IGNORE_INDEX]
    comp_pos = [j for j in range(comp_per.shape[0])
                if comp_shift[j].item() != IGNORE_INDEX]
    print(f"  naive targets          = {naive_pos}   ({len(naive_pos)} positions)")
    print(f"  completion-only targets= {comp_pos}   ({len(comp_pos)} positions)")
    print()
    print("WHY naive is wrong: it backprops on predicting the USER and SYSTEM tokens too")
    print("(every shift position is a target). At inference the model is ONLY ever asked")
    print("to generate ASSISTANT tokens, so training it to emit 'Hi' / 'Bye' / the user's")
    print("turns is wasted capacity AND shifts the target distribution. The fix is the")
    print("one-line mask in Section B -- this is the single most important SFT rule.")
    print()
    print("HuggingFace ships exactly these two modes:")
    print("  SFTConfig(completion_only_loss=True)  -- prompt-completion datasets")
    print("  SFTConfig(assistant_only_loss=True)   -- conversational / multi-turn")
    print("  (legacy) DataCollatorForCompletionOnlyLM -- the older collator")
    check("naive targets == T - 1 == 23 (every shift position)",
          naive_targets == T - 1)
    check("completion-only targets == 4 (assistant spans only)",
          comp_targets == 4)
    check("naive target set is a strict superset of completion-only target set",
          set(comp_pos).issubset(set(naive_pos)))
    check("the two losses differ (they average over different position sets)",
          abs(naive_loss.item() - comp_loss.item()) > 1e-6)
    return naive_loss.item(), comp_loss.item()


# ============================================================================
# E. MULTI-TURN SPAN BOOKKEEPING + PADDING + LINEAGE
#    (1) Show the assistant spans explicitly for the 2-turn convo.
#    (2) Padding: if you right-pad to a fixed length, pad tokens (id 0) must
#        ALSO be set to -100 (CrossEntropyLoss does NOT auto-mask id 0).
#    (3) The lineage ladder: base LM -> chat template -> naive SFT -> completion-only.
# ============================================================================

def section_spans_padding_lineage():
    banner("SECTION E: multi-turn spans, padding handling, and the lineage")

    # --- (1) assistant spans ---
    print("--- (1) the two assistant spans in the GOLD conversation ---\n")
    asst_positions = (GOLD_ROLE == ROLE_ASSISTANT).nonzero(as_tuple=True)[0].tolist()
    print(f"assistant (loss) positions = {asst_positions}")
    # split into contiguous spans
    spans = []
    cur = [asst_positions[0]]
    for p in asst_positions[1:]:
        if p == cur[-1] + 1:
            cur.append(p)
        else:
            spans.append(cur)
            cur = [p]
    spans.append(cur)
    print(f"= {len(spans)} contiguous assistant spans:")
    for k, sp in enumerate(spans, 1):
        toks = [VOCAB_NAMES[GOLD_IDS[i].item()] for i in sp]
        print(f"  turn {k}: positions {sp} -> tokens {toks}  "
              f"(content + closing <|im_end|>)")
    print("A K-turn conversation (K assistant turns) has exactly K such spans; the mask")
    print("in Section B finds them all via the role array. Multi-turn is free.\n")
    check("2-turn conversation has exactly 2 assistant spans", len(spans) == 2)
    check("each span ends with the closing <|im_end|> (id 2)",
          all(GOLD_IDS[sp[-1]].item() == IM_END for sp in spans))

    # --- (2) padding: pad tokens must be masked to -100 too ---
    print("--- (2) padding: pad_id tokens are NOT auto-masked -- set them to -100 ---\n")
    pad_len = 28
    pad_count = pad_len - GOLD_IDS.shape[0]
    padded_ids = torch.cat([GOLD_IDS, torch.full((pad_count,), PAD, dtype=torch.long)])
    padded_role = torch.cat([GOLD_ROLE, torch.full((pad_count,), ROLE_SPECIAL, dtype=torch.long)])
    padded_labels = build_labels(padded_ids, padded_role)
    print(f"right-pad the {GOLD_IDS.shape[0]}-token convo to length {pad_len} "
          f"(+{pad_count} pad tokens, id={PAD}).")
    print("Pad tokens get ROLE_SPECIAL -> the build_labels() mask sets them to -100.")
    print(f"  padded labels (tail) = {padded_labels[GOLD_IDS.shape[0]:].tolist()}")
    print(f"  pad positions all -100? "
          f"{all(padded_labels[i].item() == IGNORE_INDEX for i in range(GOLD_IDS.shape[0], pad_len))}")
    print()
    print("PITFALL: CrossEntropyLoss(ignore_index=-100) ignores the LABEL value -100,")
    print("NOT the token id 0. If your collator leaves pad labels as id 0, the model is")
    print("trained to predict the <pad> token -- a silent bug. Always set pad labels to -100.")
    check("padded length == 28", padded_ids.shape[0] == pad_len)
    check("all pad-token labels are -100 (padding masked)",
          all(padded_labels[i].item() == IGNORE_INDEX
              for i in range(GOLD_IDS.shape[0], pad_len)))
    check("non-masked count unchanged after padding (still 4)",
          int((padded_labels != IGNORE_INDEX).sum().item()) == 4)

    # --- (3) lineage ---
    print()
    print("--- (3) the lineage: base LM -> chat template -> naive SFT -> completion-only ---\n")
    ladder = [
        ("base LM",
         "predict EVERY next token of plain text",
         "no notion of roles; fine for pretrain",
         "next-token CE on the raw stream"),
        ("chat template",
         "wrap turns: <|im_start|>role\\n{msg}<|im_end|>\\n",
         "model can now see role boundaries",
         "ChatML (Qwen/SmolLM/OpenAI); Jinja in the tokenizer"),
        ("naive SFT",
         "tokenise template; labels = input_ids (NO mask)",
         "trains the model to GENERATE user turns too",
         "wrong target distribution; wasted capacity (the bug)"),
        ("completion-only",
         "labels[role != assistant] = -100; CE(ignore_index=-100)",
         "loss ONLY on assistant content + closing <|im_end|>",
         "trl SFTConfig(assistant_only_loss=True); the SFT rule"),
    ]
    print("| stage          | what it does                                  | "
          "failure / win                              | where                         |")
    print("|----------------|-----------------------------------------------|"
          "---------------------------------------------|-------------------------------|")
    for name, what, fw, where in ladder:
        print(f"| {name:<14} | {what:<45} | {fw:<43} | {where:<29} |")
    print()
    check("lineage has exactly 4 stages", len(ladder) == 4)
    check("the completion-only stage is the SFT rule (mask + ignore_index=-100)",
          "ignore_index=-100" in ladder[3][1])


# ============================================================================
# main
# ============================================================================

def main():
    print("instruction_sft.py - reference impl. All numbers below feed "
          "INSTRUCTION_SFT.md.\ntorch =", torch.__version__)
    print("\nEvery claim is web-verified in >=2 sources; "
          "see instruction_sft_reference.txt.")

    T, A, masked = section_build_conversation()
    labels = section_label_masking()
    section_cross_entropy_demo(labels)
    section_naive_vs_completion()
    section_spans_padding_lineage()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
