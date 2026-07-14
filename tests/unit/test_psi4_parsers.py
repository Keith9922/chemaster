"""calc_psi4/parsers.py 的纯解析测试 — 不依赖 psi4，可在任意 CI 环境跑。

（server.py 的测试要 mock psi4 模块，在无 psi4 的 runner 上整体跳过；
拆出解析器后，这部分覆盖不再受 psi4 缺席影响。）
"""

from __future__ import annotations

from chemaster.mcp.calc_psi4.parsers import (
    get_ir_intensities,
    parse_frequencies_from_output,
    parse_opt_iterations_from_output,
    parse_tdscf_from_output,
    parse_thermal_from_output,
)


def test_frequencies_new_format_multi_irrep(tmp_path):
    log = tmp_path / "freq.log"
    log.write_text(
        "  Freq [cm^-1]                1618.2540           3834.8812\n"
        "  some other line\n"
        "  Freq [cm^-1]                3931.8836\n"
    )
    assert parse_frequencies_from_output(str(log)) == [
        1618.254, 3834.8812, 3931.8836,
    ]


def test_frequencies_legacy_format_and_missing_file(tmp_path):
    log = tmp_path / "old.log"
    log.write_text("  Frequency   -52.1000\n  Frequency  1500.0000\n")
    assert parse_frequencies_from_output(str(log)) == [-52.1, 1500.0]
    assert parse_frequencies_from_output(str(tmp_path / "nope.log")) == []


def test_thermal_block_roundtrip(tmp_path):
    log = tmp_path / "thermo.log"
    log.write_text(
        "  Correction H    15.928 [kcal/mol]   66.6 [kJ/mol]   0.02538285 [Eh]\n"
        "  Total H, Enthalpy at  298.15 [K]   -76.33282512 [Eh]\n"
        "  Correction G     2.488 [kcal/mol]   10.4 [kJ/mol]   0.00396527 [Eh]\n"
        "  Total G, Gibbs energy at  298.15 [K]   -76.35424270 [Eh]\n"
    )
    out = parse_thermal_from_output(str(log))
    assert out["h_corr"] == {"value": 0.02538285, "unit": "Hartree"}
    assert out["total_g"] == {"value": -76.35424270, "unit": "Hartree"}
    # T·S = H_corr − G_corr
    assert abs(out["ts"]["value"] - (0.02538285 - 0.00396527)) < 1e-9
    assert out["e_corr"] is None


def test_tdscf_split_singlets_triplets_and_dedup(tmp_path):
    log = tmp_path / "td.log"
    block = (
        "  Excited State    1 (1 A):   0.30000 au   151.98 nm f = 0.0123\n"
        "  Excited State    2 (3 A):   0.25504 au   178.65 nm f = 0.0000\n"
    )
    log.write_text(block + block)  # psi4 会打印两遍 → 需去重
    singlets, triplets = parse_tdscf_from_output(str(log), want_triplets=True)
    assert len(singlets) == 1 and len(triplets) == 1
    assert singlets[0]["state"] == 1
    assert singlets[0]["excitation_energy"]["unit"] == "eV"
    assert abs(singlets[0]["excitation_energy"]["value"] - 0.3 * 27.2114) < 0.01
    # 不要三重态时被过滤
    s_only, t_none = parse_tdscf_from_output(str(log), want_triplets=False)
    assert t_none == []


def test_opt_iterations_banner_and_fallback(tmp_path):
    log = tmp_path / "opt.log"
    log.write_text(
        "OPTKING 3.0: for geometry optimizations\nblah\n"
        "OPTKING 3.0: for geometry optimizations\n"
    )
    assert parse_opt_iterations_from_output(str(log)) == 2
    log.write_text("Optimization Iteration 1\nOptimization Iteration 2\n"
                   "Optimization Iteration 3\n")
    assert parse_opt_iterations_from_output(str(log)) == 3


def test_ir_intensities_fallback_zero():
    class NoFA:
        frequency_analysis = None

    assert get_ir_intensities(NoFA(), 3) == [0.0, 0.0, 0.0]


def test_ir_intensities_from_wfn():
    class Data:
        def tolist(self):
            return [1.5, 2.5]

    class FA(dict):
        pass

    class Wfn:
        frequency_analysis = FA(IR_intensity=type("X", (), {"data": Data()})())

    assert get_ir_intensities(Wfn(), 2) == [1.5, 2.5]
