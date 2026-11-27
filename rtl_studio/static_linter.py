"""Verilator/Icarus lint wrapper + complementary SystemVerilog static analyzer."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from contracts.hdl_models import LintReport, LintWarning
from contracts.toolchain import build_eda_env, find_tool

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")

_SV_KEYWORDS = {
    "module",
    "endmodule",
    "input",
    "output",
    "inout",
    "logic",
    "wire",
    "reg",
    "signed",
    "unsigned",
    "parameter",
    "localparam",
    "integer",
    "int",
    "bit",
    "typedef",
    "enum",
    "always_ff",
    "always_comb",
    "always",
    "posedge",
    "negedge",
    "or",
    "if",
    "else",
    "case",
    "casez",
    "casex",
    "endcase",
    "default",
    "begin",
    "end",
    "for",
    "assign",
    "function",
    "endfunction",
    "return",
}


def _strip_comments_preserve_lines(source: str) -> str:
    """Replace comments with spaces while keeping exact line numbers intact."""

    def _replace_block(match: re.Match[str]) -> str:
        text = match.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in text)

    no_block = _BLOCK_COMMENT_RE.sub(_replace_block, source)
    return _LINE_COMMENT_RE.sub("", no_block)


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _extract_balanced_block(text: str, start_idx: int) -> tuple[str, int]:
    """Extract a procedural body starting after header (either begin..end or single statement)."""
    n = len(text)
    idx = start_idx
    while idx < n and text[idx].isspace():
        idx += 1

    if text.startswith("begin", idx) and (idx + 5 == n or not (text[idx + 5].isalnum() or text[idx + 5] == "_")):
        depth = 0
        token_re = re.compile(r"\b(begin|end|case|casez|casex|endcase)\b")
        pos = idx
        while pos < n:
            m = token_re.search(text, pos)
            if not m:
                return text[idx:], n
            tok = m.group(1)
            if tok == "begin":
                depth += 1
            elif tok == "end":
                depth -= 1
                if depth == 0:
                    return text[idx : m.end()], m.end()
            pos = m.end()
        return text[idx:], n

    # Single statement ending at ';' or 'endcase'
    semi = text.find(";", idx)
    if semi == -1:
        return text[idx:], n
    return text[idx : semi + 1], semi + 1


def _eval_simple_width(msb_expr: str, lsb_expr: str, params: dict[str, int]) -> int | None:
    """Evaluate [MSB:LSB] width when MSB/LSB are constants or known parameters."""
    expr_m = msb_expr.strip()
    expr_l = lsb_expr.strip()
    for pname, pval in sorted(params.items(), key=lambda kv: -len(kv[0])):
        expr_m = re.sub(rf"\b{re.escape(pname)}\b", str(pval), expr_m)
        expr_l = re.sub(rf"\b{re.escape(pname)}\b", str(pval), expr_l)
    if re.fullmatch(r"[0-9+\-*/() ]+", expr_m) and re.fullmatch(r"[0-9+\-*/() ]+", expr_l):
        try:
            msb = int(eval(expr_m, {"__builtins__": {}}, {}))  # noqa: S307
            lsb = int(eval(expr_l, {"__builtins__": {}}, {}))  # noqa: S307
            return abs(msb - lsb) + 1
        except Exception:
            return None
    return None


def _literal_width(rhs: str) -> int | None:
    """Return bit width if rhs is an explicit sized Verilog literal like 4'b1010 or 8'hFF."""
    s = rhs.strip()
    m = re.fullmatch(r"(\d+)\s*'\s*s?[bdhoBDHO][0-9a-fA-FxXzZ_?]+", s)
    if m:
        return int(m.group(1))
    return None


def _strip_condition_parens(stmt_chunk: str) -> str:
    """Mask (...) after if/for/while/case so '<=' comparisons inside conditions aren't mistaken for assignments."""
    out = list(stmt_chunk)
    kw_re = re.compile(r"\b(if|for|while|case|casez|casex)\b")
    pos = 0
    n = len(stmt_chunk)
    while pos < n:
        m = kw_re.search(stmt_chunk, pos)
        if not m:
            break
        p = m.end()
        while p < n and stmt_chunk[p].isspace():
            p += 1
        if p < n and stmt_chunk[p] == "(":
            depth = 0
            q = p
            while q < n:
                if stmt_chunk[q] == "(":
                    depth += 1
                elif stmt_chunk[q] == ")":
                    depth -= 1
                    out[q] = " "
                    if depth == 0:
                        break
                if depth > 0 and out[q] != "\n":
                    out[q] = " "
                q += 1
            pos = q + 1
        else:
            pos = p + 1
    return "".join(out)


def _check_comb_latch_free(body: str) -> tuple[set[str], set[str], bool]:
    """Return (all_assigned_signals, top_level_defaulted_signals, has_incomplete_case).

    In strict RTL style, every signal assigned in an always_comb block should either:
    1) have an unconditional top-level default assignment before any if/case, OR
    2) be exhaustively assigned across complete if/else or case+default branches.
    """
    masked = _strip_condition_parens(body)
    # Remove outer begin/end wrapper
    inner = masked.strip()
    if inner.startswith("begin"):
        inner = inner[5:]
        if inner.endswith("end"):
            inner = inner[:-3]

    # Collect all blocking assignments `sig[...] = ...` or `sig = ...`
    assign_re = re.compile(r"(?<![=!<>])\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*=(?!=)")
    all_assigned = {
        m.group(1)
        for m in assign_re.finditer(inner)
        if m.group(1) not in _SV_KEYWORDS
    }

    # Find offset of first control-flow branching token (`if`, `case`, `casez`, `casex`) at top level
    branch_m = re.search(r"\b(if|case|casez|casex)\b", inner)
    prefix = inner[: branch_m.start()] if branch_m else inner
    defaulted = {
        m.group(1)
        for m in assign_re.finditer(prefix)
        if m.group(1) not in _SV_KEYWORDS
    }

    # Check if every `case` has a `default`
    case_count = len(re.findall(r"\b(?:case|casez|casex)\b", inner))
    default_count = len(re.findall(r"\bdefault\s*:", inner))
    incomplete_case = case_count > default_count

    # For signals not defaulted at the top, verify if a single complete if/else or complete case assigns them in every branch
    fully_covered_non_default: set[str] = set()
    remaining = all_assigned - defaulted
    if remaining and branch_m:
        # Check simple if (...) ... else ... completeness when there is at least one `else`
        has_if = bool(re.search(r"\bif\b", inner))
        if_count = len(re.findall(r"\bif\b", inner))
        else_count = len(re.findall(r"\belse\b", inner))
        if has_if and else_count >= if_count and case_count == 0:
            # Split around top-level `else` when single if/else
            parts = re.split(r"\belse\b", inner)
            if len(parts) >= 2:
                per_branch = [
                    {
                        m.group(1)
                        for m in assign_re.finditer(p)
                        if m.group(1) not in _SV_KEYWORDS
                    }
                    for p in parts
                ]
                common = set.intersection(*per_branch) if per_branch else set()
                fully_covered_non_default |= common

    safe_signals = defaulted | fully_covered_non_default
    latched_signals = all_assigned - safe_signals
    return latched_signals, all_assigned, incomplete_case


def _analyze_single_sv_file(sv_path: Path) -> tuple[list[LintWarning], dict[str, int]]:
    """Complementary AST-lite SystemVerilog static rule checker."""
    raw = sv_path.read_text(encoding="utf-8")
    clean = _strip_comments_preserve_lines(raw)
    warnings: list[LintWarning] = []
    counts = {
        "inferred_latches": 0,
        "blocking_in_seq": 0,
        "nonblocking_in_comb": 0,
        "missing_reset_clauses": 0,
        "undriven_nets": 0,
        "multidriven_nets": 0,
        "width_mismatches": 0,
    }

    # Analyze each module in the file
    mod_re = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)\b(.*?)\bendmodule\b", re.DOTALL)
    for mod_m in mod_re.finditer(clean):
        mod_body = mod_m.group(2)
        mod_offset = mod_m.start(2)

        # 1. Extract parameters / localparams with integer values
        params: dict[str, int] = {}
        param_re = re.compile(
            r"\b(?:parameter|localparam)\b[^;=]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([0-9_]+)\b"
        )
        for pm in param_re.finditer(mod_body):
            try:
                params[pm.group(1)] = int(pm.group(2).replace("_", ""))
            except ValueError:
                pass

        # 2. Extract typedef enum widths & enum literal names
        typedef_widths: dict[str, int] = {}
        enum_literals: set[str] = set()
        enum_re = re.compile(
            r"\btypedef\s+enum\s+logic\s*(?:\[\s*([^:\]]+)\s*:\s*([^\]]+)\s*\])?\s*\{([^}]*)\}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;",
            re.DOTALL,
        )
        for em in enum_re.finditer(mod_body):
            w = 32
            if em.group(1) is not None and em.group(2) is not None:
                eval_w = _eval_simple_width(em.group(1), em.group(2), params)
                w = eval_w if eval_w is not None else 1
            tname = em.group(4)
            typedef_widths[tname] = w
            for item in em.group(3).split(","):
                lit = item.split("=")[0].strip()
                if lit and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", lit):
                    enum_literals.add(lit)

        # 3. Extract ports and internal signals
        port_dirs: dict[str, str] = {}
        sig_widths: dict[str, int | None] = {}
        is_array: set[str] = set()

        port_decl_re = re.compile(
            r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(?:signed|unsigned)?\s*"
            r"(?:\[\s*([^:\]]+)\s*:\s*([^\]]+)\s*\])?\s*([A-Za-z_][A-Za-z0-9_]*)\b"
        )
        for pm in port_decl_re.finditer(mod_body):
            pdir, msb, lsb, pname = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
            if pname in _SV_KEYWORDS:
                continue
            port_dirs[pname] = pdir
            if msb is not None and lsb is not None:
                sig_widths[pname] = _eval_simple_width(msb, lsb, params)
            else:
                sig_widths[pname] = 1

        # Internal logic/reg/wire declarations (excluding typedef enum bodies)
        body_no_typedefs = enum_re.sub(lambda m: "\n" * m.group(0).count("\n"), mod_body)
        decl_stmt_re = re.compile(
            r"(?<!input\s)(?<!output\s)(?<!inout\s)\b(?:logic|wire|reg)\b\s*(?:signed|unsigned)?\s*"
            r"(?:\[\s*([^:\]]+)\s*:\s*([^\]]+)\s*\])?\s*([^;]+);"
        )
        for dm in decl_stmt_re.finditer(body_no_typedefs):
            prefix_before = body_no_typedefs[max(0, dm.start() - 25) : dm.start()]
            if re.search(r"\b(input|output|inout|typedef|function)\s*$", prefix_before):
                continue
            msb, lsb, names_chunk = dm.group(1), dm.group(2), dm.group(3)
            w = _eval_simple_width(msb, lsb, params) if (msb is not None and lsb is not None) else 1
            for raw_item in names_chunk.split(","):
                item = raw_item.split("=")[0].strip()
                arr_m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(\[[^\]]+\])?$", item)
                if arr_m:
                    sname = arr_m.group(1)
                    if sname not in _SV_KEYWORDS and sname not in port_dirs and sname not in enum_literals:
                        sig_widths[sname] = w
                        if arr_m.group(2):
                            is_array.add(sname)

        # Custom typedef declarations (e.g. `state_t state, next_state;`)
        for tname, tw in typedef_widths.items():
            tdecl_re = re.compile(rf"\b{re.escape(tname)}\b\s+([^;]+);")
            for tm in tdecl_re.finditer(mod_body):
                for raw_item in tm.group(1).split(","):
                    sname = raw_item.split("=")[0].strip()
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", sname):
                        sig_widths[sname] = tw

        # Identify reset port if present
        reset_ports = [
            p
            for p, d in port_dirs.items()
            if d == "input" and any(tok in p.lower() for tok in ("rst", "reset"))
        ]

        # Track signal drivers across blocks: signal -> list of block_ids
        signal_drivers: dict[str, list[tuple[str, int]]] = {}

        def _record_driver(
            sig: str,
            block_id: str,
            line_no: int,
            _params: dict[str, int] = params,
            _enums: set[str] = enum_literals,
            _widths: dict[str, int | None] = sig_widths,
            _pdirs: dict[str, str] = port_dirs,
            _drivers: dict[str, list[tuple[str, int]]] = signal_drivers,
        ) -> None:
            if sig in _SV_KEYWORDS or sig in _params or sig in _enums:
                return
            if sig not in _widths and sig not in _pdirs:
                return
            lst = _drivers.setdefault(sig, [])
            if not any(bid == block_id for bid, _ in lst):
                lst.append((block_id, line_no))

        # 4. Inspect sequential blocks: always_ff or always @(posedge/negedge ...)
        seq_re = re.compile(
            r"\b(always_ff\s*@\s*\(([^)]*)\)|always\s*@\s*\(([^)]*(?:posedge|negedge)[^)]*)\))"
        )
        block_counter = 0
        for sm in seq_re.finditer(mod_body):
            block_counter += 1
            bid = f"seq_{block_counter}"
            sens = sm.group(2) if sm.group(2) is not None else (sm.group(3) or "")
            blk_line = _line_of_offset(clean, mod_offset + sm.start())
            body, _ = _extract_balanced_block(mod_body, sm.end())
            masked_body = _strip_condition_parens(body)

            # Check blocking assignments `=` inside sequential block
            seq_assigned_non_array: set[str] = set()
            blk_assign_re = re.compile(
                r"(?<![=!<>])\b([A-Za-z_][A-Za-z0-9_]*)(\s*\[[^\]]*\])?\s*=(?!=)\s*([^;]+);"
            )
            for bm in blk_assign_re.finditer(masked_body):
                sig = bm.group(1)
                idx_part = bm.group(2)
                rhs = bm.group(3)
                if sig in _SV_KEYWORDS:
                    continue
                line_no = _line_of_offset(clean, mod_offset + sm.end() + bm.start())
                counts["blocking_in_seq"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error",
                        code="BLKSEQ",
                        message=f"Blocking assignment '=' used on '{sig}' inside sequential always_ff block.",
                        file=str(sv_path),
                        line=line_no,
                        signal=sig,
                    )
                )
                _record_driver(sig, bid, line_no)
                if sig not in is_array:
                    seq_assigned_non_array.add(sig)
                if not idx_part and sig in sig_widths and sig_widths[sig] is not None:
                    lit_w = _literal_width(rhs)
                    if lit_w is not None and lit_w != sig_widths[sig]:
                        counts["width_mismatches"] += 1
                        warnings.append(
                            LintWarning(
                                tool="static_analyzer",
                                severity="warning",
                                code="WIDTH_MISMATCH",
                                message=(
                                    f"Width mismatch on '{sig}': signal is {sig_widths[sig]} bits "
                                    f"but assigned {lit_w}-bit literal '{rhs.strip()}'."
                                ),
                                file=str(sv_path),
                                line=line_no,
                                signal=sig,
                            )
                        )

            # Collect non-blocking assignments `<=`
            nb_assign_re = re.compile(
                r"\b([A-Za-z_][A-Za-z0-9_]*)(\s*\[[^\]]*\])?\s*<=\s*([^;]+);"
            )
            for nbm in nb_assign_re.finditer(masked_body):
                sig = nbm.group(1)
                idx_part = nbm.group(2)
                rhs = nbm.group(3)
                line_no = _line_of_offset(clean, mod_offset + sm.end() + nbm.start())
                _record_driver(sig, bid, line_no)
                if sig not in is_array:
                    seq_assigned_non_array.add(sig)
                # Static literal width check when whole signal (not bit-select) is assigned
                if not idx_part and sig in sig_widths and sig_widths[sig] is not None:
                    lit_w = _literal_width(rhs)
                    if lit_w is not None and lit_w != sig_widths[sig]:
                        counts["width_mismatches"] += 1
                        warnings.append(
                            LintWarning(
                                tool="static_analyzer",
                                severity="warning",
                                code="WIDTH_MISMATCH",
                                message=(
                                    f"Width mismatch on '{sig}': signal is {sig_widths[sig]} bits "
                                    f"but assigned {lit_w}-bit literal '{rhs.strip()}'."
                                ),
                                file=str(sv_path),
                                line=line_no,
                                signal=sig,
                            )
                        )

            # Check reset clause if module declares a reset port and block assigns non-array registers
            if reset_ports and seq_assigned_non_array:
                has_rst_check = any(
                    re.search(rf"\b{re.escape(rp)}\b", body) for rp in reset_ports
                )
                if not has_rst_check:
                    counts["missing_reset_clauses"] += 1
                    warnings.append(
                        LintWarning(
                            tool="static_analyzer",
                            severity="warning",
                            code="MISSING_RESET",
                            message=(
                                f"Sequential block at line {blk_line} lacks reset handling for "
                                f"{sorted(seq_assigned_non_array)} (reset port: {reset_ports[0]})."
                            ),
                            file=str(sv_path),
                            line=blk_line,
                            signal=sorted(seq_assigned_non_array)[0],
                        )
                    )
                elif any(rp in sens for rp in reset_ports):
                    # Verify async reset sensitivity polarity matches condition if (!rst_n) -> negedge rst_n
                    for rp in reset_ports:
                        if f"negedge {rp}" in sens and re.search(rf"\bif\s*\(\s*{re.escape(rp)}\s*\)", body):
                            counts["missing_reset_clauses"] += 1
                            warnings.append(
                                LintWarning(
                                    tool="static_analyzer",
                                    severity="error",
                                    code="MISSING_RESET",
                                    message=f"Polarity mismatch: sensitivity has 'negedge {rp}' but reset checks '{rp}' active-high.",
                                    file=str(sv_path),
                                    line=blk_line,
                                    signal=rp,
                                )
                            )

        # 5. Inspect combinational blocks: always_comb or always @(*)
        comb_re = re.compile(r"\b(always_comb\b|always\s*@\s*\(\s*\*?\s*\))")
        for cm in comb_re.finditer(mod_body):
            block_counter += 1
            bid = f"comb_{block_counter}"
            blk_line = _line_of_offset(clean, mod_offset + cm.start())
            body, _ = _extract_balanced_block(mod_body, cm.end())
            masked_body = _strip_condition_parens(body)

            # Non-blocking `<=` statement assignment inside combinational block (ignoring `<=` inside RHS parens)
            stmt_lhs_nb_re = re.compile(
                r"(?:^|[;{}]|\bbegin\b|\belse\b)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*<=",
                re.MULTILINE,
            )
            for nbm in stmt_lhs_nb_re.finditer(masked_body):
                sig = nbm.group(1)
                if sig in _SV_KEYWORDS:
                    continue
                line_no = _line_of_offset(clean, mod_offset + cm.end() + nbm.start())
                counts["nonblocking_in_comb"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error",
                        code="NONBLKCOMB",
                        message=f"Non-blocking assignment '<=' used on '{sig}' inside combinational block.",
                        file=str(sv_path),
                        line=line_no,
                        signal=sig,
                    )
                )

            latched_sigs, all_comb_sigs, incomplete_case = _check_comb_latch_free(body)
            for sig in sorted(all_comb_sigs):
                _record_driver(sig, bid, blk_line)

            for sig in sorted(latched_sigs):
                counts["inferred_latches"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error",
                        code="LATCH_INFERRED",
                        message=(
                            f"Potential inferred latch on '{sig}' in always_comb at line {blk_line}: "
                            "missing explicit default assignment at top of always_comb or incomplete branch."
                        ),
                        file=str(sv_path),
                        line=blk_line,
                        signal=sig,
                    )
                )
            if incomplete_case and not latched_sigs:
                counts["inferred_latches"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="warning",
                        code="CASE_INCOMPLETE",
                        message=f"Case statement without 'default:' branch in always_comb at line {blk_line}.",
                        file=str(sv_path),
                        line=blk_line,
                    )
                )

            # Check literal width mismatches in combinational assignments
            comb_assign_re = re.compile(
                r"(?<![=!<>])\b([A-Za-z_][A-Za-z0-9_]*)(\s*\[[^\]]*\])?\s*=(?!=)\s*([^;]+);"
            )
            for cam in comb_assign_re.finditer(masked_body):
                sig, idx_part, rhs = cam.group(1), cam.group(2), cam.group(3)
                if not idx_part and sig in sig_widths and sig_widths[sig] is not None:
                    lit_w = _literal_width(rhs)
                    if lit_w is not None and lit_w != sig_widths[sig]:
                        line_no = _line_of_offset(clean, mod_offset + cm.end() + cam.start())
                        counts["width_mismatches"] += 1
                        warnings.append(
                            LintWarning(
                                tool="static_analyzer",
                                severity="warning",
                                code="WIDTH_MISMATCH",
                                message=(
                                    f"Width mismatch on '{sig}': signal is {sig_widths[sig]} bits "
                                    f"but assigned {lit_w}-bit literal '{rhs.strip()}'."
                                ),
                                file=str(sv_path),
                                line=line_no,
                                signal=sig,
                            )
                        )

        # 6. Continuous `assign` statements
        cont_re = re.compile(
            r"\bassign\s+([A-Za-z_][A-Za-z0-9_]*)(\s*\[[^\]]*\])?\s*=\s*([^;]+);"
        )
        for am in cont_re.finditer(mod_body):
            block_counter += 1
            sig, idx_part, rhs = am.group(1), am.group(2), am.group(3)
            line_no = _line_of_offset(clean, mod_offset + am.start())
            _record_driver(sig, f"assign_{block_counter}_{idx_part or 'full'}", line_no)
            if not idx_part and sig in sig_widths and sig_widths[sig] is not None:
                lit_w = _literal_width(rhs)
                if lit_w is not None and lit_w != sig_widths[sig]:
                    counts["width_mismatches"] += 1
                    warnings.append(
                        LintWarning(
                            tool="static_analyzer",
                            severity="warning",
                            code="WIDTH_MISMATCH",
                            message=(
                                f"Width mismatch on continuous assign '{sig}': signal is {sig_widths[sig]} bits "
                                f"but assigned {lit_w}-bit literal '{rhs.strip()}'."
                            ),
                            file=str(sv_path),
                            line=line_no,
                            signal=sig,
                        )
                    )

        # 7. Submodule port connections (`.port(sig)`) — treat connected non-input signals as potentially driven if not driven elsewhere
        subconn_sigs: set[str] = set()
        for scm in re.finditer(r"\.[A-Za-z_][A-Za-z0-9_]*\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)", mod_body):
            subconn_sigs.add(scm.group(1))

        # 8. Check multi-driven nets, driven inputs, and undriven outputs/internal nets
        for sig, drivers in signal_drivers.items():
            if port_dirs.get(sig) == "input":
                counts["multidriven_nets"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error",
                        code="MULTIDRIVEN_NET",
                        message=f"Input port '{sig}' is illegally driven inside module.",
                        file=str(sv_path),
                        line=drivers[0][1],
                        signal=sig,
                    )
                )
            elif len(drivers) > 1:
                counts["multidriven_nets"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error",
                        code="MULTIDRIVEN_NET",
                        message=f"Signal '{sig}' has multiple procedural/continuous drivers ({len(drivers)} blocks).",
                        file=str(sv_path),
                        line=drivers[1][1],
                        signal=sig,
                    )
                )

        for sig in sorted(sig_widths):
            pdir = port_dirs.get(sig)
            if pdir == "input":
                continue
            if sig not in signal_drivers and sig not in subconn_sigs:
                counts["undriven_nets"] += 1
                warnings.append(
                    LintWarning(
                        tool="static_analyzer",
                        severity="error" if pdir == "output" else "warning",
                        code="UNDRIVEN_NET",
                        message=f"{'Output port' if pdir == 'output' else 'Internal signal'} '{sig}' has no driver.",
                        file=str(sv_path),
                        signal=sig,
                    )
                )

    return warnings, counts


def _run_verilator_lint(
    rtl_files: list[Path], top_module: str | None, env: dict[str, str]
) -> tuple[list[LintWarning], dict[str, int], bool]:
    """Run `verilator --lint-only -Wall` in an isolated temp workspace if available."""
    vbin = shutil.which("verilator_bin", path=env.get("PATH"))
    vtool = vbin or find_tool("verilator", env)
    if not vtool:
        return [], {}, False

    warnings: list[LintWarning] = []
    extra_counts = {"inferred_latches": 0, "width_mismatches": 0, "blocking_in_seq": 0, "multidriven_nets": 0, "undriven_nets": 0}
    with tempfile.TemporaryDirectory(prefix="autopilot_vlint_") as tmpdir:
        staged_names: list[str] = []
        for f in rtl_files:
            dst = Path(tmpdir) / f.name
            shutil.copy2(f, dst)
            staged_names.append(f.name)

        cmd = [vtool, "--lint-only", "-Wall", "-sv"]
        if top_module:
            cmd.extend(["--top-module", top_module])
        cmd.extend(staged_names)

        proc = subprocess.run(
            cmd,
            cwd=tmpdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        diag_re = re.compile(
            r"^%(Error|Warning)(?:-([A-Z0-9_]+))?:\s*((?:[A-Za-z]:)?[^:]+):(\d+):(?:\d+:)?\s*(.+)$"
        )
        for raw_line in combined.splitlines():
            line = raw_line.strip()
            m = diag_re.match(line)
            if not m:
                continue
            sev_raw, code_raw, fname, line_s, msg = m.groups()
            code = code_raw or "VERILATOR_ERROR"
            if code in ("PKGNODECL",):
                pass
            sev = "error" if sev_raw == "Error" else "warning"
            warnings.append(
                LintWarning(
                    tool="verilator",
                    severity=sev,
                    code=code,
                    message=msg.strip(),
                    file=Path(fname).name,
                    line=int(line_s),
                )
            )
            if "LATCH" in code:
                extra_counts["inferred_latches"] += 1
            elif "WIDTH" in code:
                extra_counts["width_mismatches"] += 1
            elif code == "BLKSEQ":
                extra_counts["blocking_in_seq"] += 1
            elif "MULTIDRIVEN" in code:
                extra_counts["multidriven_nets"] += 1
            elif "UNDRIVEN" in code:
                extra_counts["undriven_nets"] += 1

        if proc.returncode != 0 and not warnings:
            warnings.append(
                LintWarning(
                    tool="verilator",
                    severity="error",
                    code="VERILATOR_FAIL",
                    message=combined.strip()[:400] or "Verilator lint returned non-zero exit status.",
                )
            )

    return warnings, extra_counts, True


def _run_iverilog_lint(
    rtl_files: list[Path], top_module: str | None, env: dict[str, str]
) -> tuple[list[LintWarning], dict[str, int], bool]:
    """Run `iverilog -g2012 -Wall` in an isolated temp workspace if available."""
    iverilog = find_tool("iverilog", env)
    if not iverilog:
        return [], {}, False

    warnings: list[LintWarning] = []
    extra_counts = {"width_mismatches": 0}
    with tempfile.TemporaryDirectory(prefix="autopilot_ilint_") as tmpdir:
        staged_names: list[str] = []
        for f in rtl_files:
            dst = Path(tmpdir) / f.name
            shutil.copy2(f, dst)
            staged_names.append(f.name)
        cmd = [iverilog, "-g2012", "-Wall", "-o", "lint.out"]
        if top_module:
            cmd.extend(["-s", top_module])
        cmd.extend(staged_names)

        proc = subprocess.run(
            cmd,
            cwd=tmpdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        diag_re = re.compile(
            r"^((?:[A-Za-z]:)?[^:]+):(\d+):\s*(warning|error|syntax error):\s*(.+)$",
            re.IGNORECASE,
        )
        for raw_line in combined.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m = diag_re.match(line)
            if m:
                fname, line_s, kind, msg = m.groups()
                sev = "warning" if kind.lower() == "warning" else "error"
                code = "IVERILOG_WARN" if sev == "warning" else "IVERILOG_ERR"
                if "width" in msg.lower() or "padding" in msg.lower() or "truncat" in msg.lower():
                    code = "WIDTH_MISMATCH"
                    extra_counts["width_mismatches"] += 1
                warnings.append(
                    LintWarning(
                        tool="iverilog",
                        severity=sev,
                        code=code,
                        message=msg.strip(),
                        file=Path(fname).name,
                        line=int(line_s),
                    )
                )
            elif "syntax error" in line.lower() or "i give up" in line.lower():
                warnings.append(
                    LintWarning(
                        tool="iverilog",
                        severity="error",
                        code="SYNTAX_ERROR",
                        message=line,
                    )
                )

        if proc.returncode != 0 and not any(w.severity == "error" for w in warnings):
            warnings.append(
                LintWarning(
                    tool="iverilog",
                    severity="error",
                    code="IVERILOG_FAIL",
                    message=combined.strip()[:400] or "iverilog failed with non-zero exit code.",
                )
            )

    return warnings, extra_counts, True


def run_static_lint(
    rtl_files: list[Path] | Path,
    top_module: str | None = None,
) -> LintReport:
    """Execute complementary static RTL analyzer + Verilator + Icarus Verilog lint."""
    files = [rtl_files] if isinstance(rtl_files, Path) else list(rtl_files)
    env = build_eda_env()

    tools_used = ["static_analyzer"]
    all_warnings: list[LintWarning] = []
    agg = {
        "inferred_latches": 0,
        "blocking_in_seq": 0,
        "nonblocking_in_comb": 0,
        "missing_reset_clauses": 0,
        "undriven_nets": 0,
        "multidriven_nets": 0,
        "width_mismatches": 0,
    }

    for f in files:
        w_list, c_map = _analyze_single_sv_file(f)
        all_warnings.extend(w_list)
        for k, v in c_map.items():
            agg[k] += v

    v_warns, v_counts, v_ran = _run_verilator_lint(files, top_module, env)
    if v_ran:
        tools_used.append("verilator")
        all_warnings.extend(v_warns)
        # Use max so duplicate detections between static_analyzer & verilator don't double-inflate,
        # while catching any issue detected by only one of the analyzers.
        for k, v in v_counts.items():
            agg[k] = max(agg[k], v)

    i_warns, i_counts, i_ran = _run_iverilog_lint(files, top_module, env)
    if i_ran:
        tools_used.append("iverilog")
        all_warnings.extend(i_warns)
        for k, v in i_counts.items():
            agg[k] = max(agg[k], v)

    error_count = sum(1 for w in all_warnings if w.severity == "error")
    warning_count = sum(1 for w in all_warnings if w.severity == "warning")

    passed = (
        error_count == 0
        and warning_count == 0
        and agg["inferred_latches"] == 0
        and agg["blocking_in_seq"] == 0
        and agg["nonblocking_in_comb"] == 0
        and agg["missing_reset_clauses"] == 0
        and agg["undriven_nets"] == 0
        and agg["multidriven_nets"] == 0
        and agg["width_mismatches"] == 0
    )

    return LintReport(
        passed=passed,
        inferred_latches=agg["inferred_latches"],
        blocking_in_seq=agg["blocking_in_seq"],
        nonblocking_in_comb=agg["nonblocking_in_comb"],
        missing_reset_clauses=agg["missing_reset_clauses"],
        undriven_nets=agg["undriven_nets"],
        multidriven_nets=agg["multidriven_nets"],
        width_mismatches=agg["width_mismatches"],
        error_count=error_count,
        warning_count=warning_count,
        tools_used=tools_used,
        warnings=all_warnings,
    )
