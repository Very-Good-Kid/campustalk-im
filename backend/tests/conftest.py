"""pytest 钩子：system_test 的逐条结果回写 test_results.json。

schema 与原生 `python system_test.py` 输出保持一致（meta + cases），
报告生成脚本可继续直接消费；runner 字段标注本次由 pytest 驱动。
原生直跑不经过 conftest，两条通道互不干扰。
"""
import datetime as dt
import json
import os

import system_test as st


def pytest_sessionfinish(session, exitstatus):
    if not st.RUNNING_PYTEST or not st.RESULTS:
        return
    passed = sum(1 for r in st.RESULTS if r["result"] == "通过")
    failed = [r for r in st.RESULTS if r["result"] == "失败"]
    out = os.path.join(os.path.dirname(__file__), "test_results.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "meta": {
                "ts": st.TS,
                "base": st.BASE, "frontend": st.FE,
                "started_at": dt.datetime.now().isoformat(),
                "total": len(st.RESULTS), "passed": passed, "failed": len(failed),
                "runner": "pytest",
            },
            "cases": st.RESULTS,
        }, fh, ensure_ascii=False, indent=2)
    print(f"\n[conftest] test_results.json 已写入：{passed}/{len(st.RESULTS)} 通过")
