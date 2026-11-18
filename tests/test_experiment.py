import json
import shutil
from argparse import Namespace

import numpy as np
import pandas as pd
import pytest

from invest_exp import experiment, forecast, report


def _fake_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(experiment, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(experiment, "RAW", tmp_path / "raw")
    (tmp_path / "processed").mkdir()
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("1999-01-05", "2016-06-15")
    level = pd.Series(1000 * np.exp((0.0003 + 0.012 * rng.standard_normal(len(idx))).cumsum()), index=idx)
    for name, is_tr in (("taiex_tr_spliced.csv", idx >= "2003-01-02"), ("taiex_price.csv", np.zeros(len(idx), bool))):
        pd.DataFrame({"level": level, "is_tr": is_tr}, index=pd.Index(idx, name="date")).to_csv(
            tmp_path / "processed" / name
        )
    run = tmp_path / "runs" / "r1"
    fdir = run / "forecasts"
    fdir.mkdir(parents=True)
    # forecasts 階段會把當時的序列快照進 run；evaluate、report 只讀這份。
    shutil.copytree(tmp_path / "processed", run / "data")
    levels = (0.01, 0.05, 0.1, 0.5, 0.9, 0.95, 0.99)
    z = {0.01: -2.33, 0.05: -1.64, 0.1: -1.28, 0.5: 0.0, 0.9: 1.28, 0.95: 1.64, 0.99: 2.33}
    prev = level.shift(1)
    for name in ("tr", "price"):
        for c in (512, 1024, 2048) if name == "tr" else (1024,):
            t = idx[c:]
            df = pd.DataFrame({forecast.qcol(q): prev.loc[t] * (1 + 0.012 * z[q]) for q in levels}, index=t)
            df.index.name = "date"
            df.insert(0, "context_end", idx[c - 1 : -1])
            df.to_csv(fdir / f"timestral_{name}_C{c}.csv")
        t = idx[1009:]
        g = pd.DataFrame({"converged": True, "q0.1": prev.loc[t] * 0.985, "q0.05": prev.loc[t] * 0.98}, index=t)
        g.index.name = "date"
        g.to_csv(fdir / f"garch_{name}.csv")
    return run


def test_evaluate_stage_end_to_end(tmp_path, monkeypatch):
    run = _fake_inputs(tmp_path, monkeypatch)
    experiment.stage_evaluate(run, n_random=3)
    experiment.write_manifest(run, Namespace(stage="evaluate", run="r1", n_random=3), "2026-11-17T00:00:00+00:00")
    out = run / "results"
    windows = pd.read_csv(out / "windows.csv")
    assert set(windows["scenario"]) == {"main", "fee0", "lag1", "price_index", "c2048"}
    main = windows[windows["scenario"] == "main"]
    assert "F_C2048_q10" not in set(main["rule"])
    # 主窗口不得早於報酬指數起點。
    assert pd.to_datetime(main["start"]).min() >= pd.Timestamp("2003-01-02")
    b0 = main[main["rule"] == "B0"]
    assert (b0["cash_end"] == 0).all()
    assert (main["final_value"] > 0).all()
    summary = pd.read_csv(out / "summary.csv")
    assert {"win_rate", "excess_median"} <= set(summary.columns)
    assert (out / "trades_main.csv.gz").exists()
    cal = pd.read_csv(out / "calibration.csv")
    assert {"F_C1024_q10", "Q_W252_q10", "G_q10"} <= set(cal["model"])
    rand = pd.read_csv(out / "random_control.csv")
    assert rand["f_percentile"].between(0, 1).all()
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["stages"][-1]["stage"] == "evaluate"
    assert "results/windows.csv" in manifest["files"]


def test_report_renders_from_run(tmp_path, monkeypatch):
    run = _fake_inputs(tmp_path, monkeypatch)
    experiment.stage_evaluate(run, n_random=3)
    experiment.write_manifest(run, Namespace(stage="evaluate", run="r1", n_random=3), "2026-11-17T00:00:00+00:00")
    html = report.render(report.build_data(run))
    assert "<title>台股分位數進場回測</title>" in html
    # 網頁版會補完整的 head；本機直接開時靠這行才不會被猜錯編碼。
    assert html.startswith('<meta charset="utf-8">')
    assert "__DATA__" not in html
    data = report.build_data(run)
    assert [h["code"] for h in data["hyp"]] == ["H1", "H2", "H3a", "H3b", "H4"]
    assert len(data["paths"]["dates"]) == len(data["paths"]["B0"])


def test_evaluate_reads_run_snapshot_not_global(tmp_path, monkeypatch):
    run = _fake_inputs(tmp_path, monkeypatch)
    # 之後重抓資料會改寫全域檔；舊 run 的評估不能跟著變。
    shutil.rmtree(tmp_path / "processed")
    experiment.stage_evaluate(run, n_random=2)
    assert (run / "results" / "windows.csv").exists()


def test_evaluate_refuses_to_overwrite_results(tmp_path, monkeypatch):
    run = _fake_inputs(tmp_path, monkeypatch)
    experiment.stage_evaluate(run, n_random=2)
    before = (run / "results" / "windows.csv").read_bytes()
    with pytest.raises(FileExistsError):
        experiment.stage_evaluate(run, n_random=2)
    assert (run / "results" / "windows.csv").read_bytes() == before


def test_legacy_run_snapshot_requires_matching_manifest(tmp_path, monkeypatch):
    run = _fake_inputs(tmp_path, monkeypatch)
    shutil.rmtree(run / "data")
    processed = tmp_path / "processed"
    good = {str(p): experiment.sha256(p) for p in sorted(processed.glob("*.csv"))}
    (run / "manifest.json").write_text(json.dumps({"data_files": {k: "0" * 64 for k in good}}))
    with pytest.raises(ValueError, match="sha256"):
        experiment.load_run_series(run)
    assert not (run / "data").exists()
    (run / "manifest.json").write_text(json.dumps({"data_files": good}))
    series = experiment.load_run_series(run)
    assert set(series) == {"tr", "price"}
    assert (run / "data" / "taiex_tr_spliced.csv").exists()
