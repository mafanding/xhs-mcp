#!/usr/bin/env python3
"""基于 CLI 调用的小红书发布功能验证脚本。

依次执行「发布 → 验证发布 → 删除 → 验证删除」，生成 JSON 与 HTML 报告。

⚠️ 这个脚本会向真实账号**发布并删除**一条笔记，请在已登录且可接受该操作的账号上运行。

用法:
    python scripts/cli_validation.py
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TEST_IMAGE_CANDIDATES = (
    "examples/images/circle.png",
    "examples/images/geometric.png",
    "examples/images/wave.png",
    "examples/images/circle.svg",
    "examples/images/geometric.svg",
    "examples/images/wave.svg",
)

_NOTE_ID_PATTERNS = (
    re.compile(r"note[_-]?id[:\s\"]+([a-f0-9]+)", re.IGNORECASE),
    re.compile(r"id[:\s\"]+([a-f0-9]{20,})", re.IGNORECASE),
    re.compile(r"([a-f0-9]{20,})"),
)


@dataclass
class TestResult:
    step: str
    success: bool
    message: str
    timestamp: int
    duration: int | None = None
    noteId: str | None = None
    title: str | None = None
    error: str | None = None


@dataclass
class CommandResult:
    success: bool
    output: str
    error: str | None


@dataclass
class CLIValidationTester:
    """跑一遍发布/删除闭环，并把每一步记录下来。"""

    cli_path: list[str] = field(default_factory=lambda: [sys.executable, "-m", "xhs_mcp"])
    test_results: list[TestResult] = field(default_factory=list)
    test_note_id: str | None = None
    test_title: str | None = None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run_validation_test(self) -> dict[str, Any]:
        print("🚀 开始小红书发布功能验证测试...")

        start_time = _now_ms()

        try:
            self.test_publish_content()
            self.test_verify_publish()
            self.test_delete_content()
            self.test_verify_delete()
        except Exception as error:
            print(f"验证测试过程中发生错误: {error}")
            self.add_result("error", False, f"测试过程中发生错误: {error}", _now_ms())

        print(f"✅ 验证测试完成，总耗时: {_now_ms() - start_time}ms")

        return self.generate_report()

    # ------------------------------------------------------------------
    # 各步骤
    # ------------------------------------------------------------------

    def test_publish_content(self) -> None:
        start_time = _now_ms()
        print("📝 开始测试发布内容...")

        try:
            test_image_path = self.get_test_image_path()
            if not test_image_path:
                raise RuntimeError("未找到测试图片")

            title = f"验证测试-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
            content = "这是一个自动化验证测试的内容，用于测试发布功能是否正常工作。"

            result = self.execute_cli_command(
                [
                    "publish",
                    "-t", "image",
                    "--title", title,
                    "--content", content,
                    "-m", test_image_path,
                    "--tags", "测试,验证,自动化",
                ]
            )

            if not result.success:
                raise RuntimeError(f"发布失败: {result.error}")

            self.test_note_id = self.extract_note_id_from_output(result.output)
            self.test_title = title

            self.add_result(
                "publish",
                True,
                f"发布成功: {result.output}",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
            )
            print(f"✅ 发布成功 - Note ID: {self.test_note_id}")
        except Exception as error:
            self.add_result(
                "publish",
                False,
                f"发布失败: {error}",
                _now_ms(),
                _now_ms() - start_time,
                error=str(error),
            )
            raise

    def test_verify_publish(self) -> None:
        start_time = _now_ms()
        print("🔍 开始验证发布成功...")

        try:
            if not self.test_note_id:
                raise RuntimeError("没有可验证的笔记ID")

            result = self.execute_cli_command(["usernote", "list"])

            if not result.success:
                raise RuntimeError("无法获取用户笔记列表")

            found = self.test_note_id in result.output or (
                self.test_title is not None and self.test_title in result.output
            )
            if not found:
                raise RuntimeError("在笔记列表中未找到刚发布的笔记")

            self.add_result(
                "verify_publish",
                True,
                f'验证发布成功: 找到笔记 "{self.test_title}"',
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
            )
            print(f"✅ 验证发布成功 - 找到笔记: {self.test_title}")
        except Exception as error:
            self.add_result(
                "verify_publish",
                False,
                f"验证发布失败: {error}",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
                str(error),
            )
            raise

    def test_delete_content(self) -> None:
        start_time = _now_ms()
        print("🗑️ 开始测试删除内容...")

        try:
            if not self.test_note_id:
                raise RuntimeError("没有可删除的笔记ID")

            result = self.execute_cli_command(
                ["usernote", "delete", "--note-id", self.test_note_id]
            )

            if not result.success:
                raise RuntimeError(f"删除失败: {result.error}")

            self.add_result(
                "delete",
                True,
                f"删除成功: {result.output}",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
            )
            print(f"✅ 删除成功 - Note ID: {self.test_note_id}")
        except Exception as error:
            self.add_result(
                "delete",
                False,
                f"删除失败: {error}",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
                str(error),
            )
            raise

    def test_verify_delete(self) -> None:
        start_time = _now_ms()
        print("🔍 开始验证删除成功...")

        try:
            if not self.test_note_id:
                raise RuntimeError("没有可验证的笔记ID")

            # 等待一段时间让删除操作生效
            time.sleep(5)

            result = self.execute_cli_command(["usernote", "list"])

            if not result.success:
                raise RuntimeError("无法获取用户笔记列表")

            still_present = self.test_note_id in result.output or (
                self.test_title is not None and self.test_title in result.output
            )
            if still_present:
                raise RuntimeError("笔记仍然存在于笔记列表中")

            self.add_result(
                "verify_delete",
                True,
                "验证删除成功: 笔记已从列表中移除",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
            )
            print("✅ 验证删除成功 - 笔记已从列表中移除")
        except Exception as error:
            self.add_result(
                "verify_delete",
                False,
                f"验证删除失败: {error}",
                _now_ms(),
                _now_ms() - start_time,
                self.test_note_id,
                self.test_title,
                str(error),
            )
            raise

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def execute_cli_command(self, args: list[str]) -> CommandResult:
        command = [*self.cli_path, *args]
        print(f"执行命令: {' '.join(command)}")

        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(False, error.stdout or "", "命令执行超时")

        if completed.returncode != 0:
            return CommandResult(
                False, completed.stdout, completed.stderr or f"exit {completed.returncode}"
            )

        return CommandResult(True, completed.stdout, None)

    @staticmethod
    def extract_note_id_from_output(output: str) -> str | None:
        for pattern in _NOTE_ID_PATTERNS:
            match = pattern.search(output)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def get_test_image_path() -> str | None:
        for candidate in _TEST_IMAGE_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return None

    def add_result(
        self,
        step: str,
        success: bool,
        message: str,
        timestamp: int,
        duration: int | None = None,
        note_id: str | None = None,
        title: str | None = None,
        error: str | None = None,
    ) -> None:
        self.test_results.append(
            TestResult(step, success, message, timestamp, duration, note_id, title, error)
        )

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------

    def generate_report(self) -> dict[str, Any]:
        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r.success)

        def step_ok(step: str) -> bool:
            return any(r.success for r in self.test_results if r.step == step)

        return {
            "testDate": datetime.now(timezone.utc).isoformat(),
            "totalTests": total,
            "passedTests": passed,
            "failedTests": total - passed,
            "results": [asdict(r) for r in self.test_results],
            "summary": {
                "publishSuccess": step_ok("publish"),
                "verifyPublishSuccess": step_ok("verify_publish"),
                "deleteSuccess": step_ok("delete"),
                "verifyDeleteSuccess": step_ok("verify_delete"),
            },
        }

    def save_report(self, report: dict[str, Any]) -> tuple[Path, Path]:
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

        json_path = reports_dir / f"cli-validation-test-{timestamp}.json"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        html_path = reports_dir / f"cli-validation-test-{timestamp}.html"
        html_path.write_text(self.generate_html_report(report), encoding="utf-8")

        print(f"📊 JSON 报告已保存到: {json_path}")
        print(f"📊 HTML 报告已保存到: {html_path}")
        return json_path, html_path

    @staticmethod
    def generate_html_report(report: dict[str, Any]) -> str:
        all_passed = all(report["summary"].values())
        total = report["totalTests"] or 1
        success_rate = f"{report['passedTests'] / total * 100:.1f}"

        def esc(value: Any) -> str:
            return html.escape(str(value))

        steps_html = "".join(
            f"""
                    <div class="step-item {'success' if r['success'] else 'error'}">
                        <div class="step-icon">{'✅' if r['success'] else '❌'}</div>
                        <div class="step-content">
                            <div class="step-title">{index}. {esc(r['step'])}</div>
                            <div class="step-message">{esc(r['message'])}</div>
                            {f'<div class="step-duration">耗时: {r["duration"]}ms</div>' if r.get('duration') else ''}
                            {f'<div class="step-message" style="color: #dc3545; margin-top: 5px;">错误: {esc(r["error"])}</div>' if r.get('error') else ''}
                        </div>
                    </div>
            """
            for index, r in enumerate(report["results"], start=1)
        )

        def function_item(icon: str, label: str, ok: bool) -> str:
            return f"""
                    <div class="function-item {'success' if ok else 'error'}">
                        <div class="function-icon">{icon}</div>
                        <div>{label}: {'✅ 正常' if ok else '❌ 异常'}</div>
                    </div>"""

        summary = report["summary"]

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小红书发布功能验证测试报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; padding: 20px;
        }}
        .container {{
            max-width: 1200px; margin: 0 auto; background: white;
            border-radius: 12px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #ff6b6b, #ff8e8e);
            color: white; padding: 30px; text-align: center;
        }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; font-weight: 700; }}
        .header .subtitle {{ font-size: 1.2em; opacity: 0.9; }}
        .content {{ padding: 30px; }}
        .summary-cards {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px; margin-bottom: 30px;
        }}
        .card {{
            background: #f8f9fa; border-radius: 8px; padding: 20px;
            text-align: center; border-left: 4px solid #007bff;
        }}
        .card.success {{ border-left-color: #28a745; background: #d4edda; }}
        .card.error {{ border-left-color: #dc3545; background: #f8d7da; }}
        .card h3 {{ font-size: 1.5em; margin-bottom: 10px; }}
        .card .value {{ font-size: 2em; font-weight: bold; color: #007bff; }}
        .card.success .value {{ color: #28a745; }}
        .card.error .value {{ color: #dc3545; }}
        .test-steps {{ margin-bottom: 30px; }}
        .test-steps h2 {{ color: #333; margin-bottom: 20px; font-size: 1.8em; }}
        .step-item {{
            display: flex; align-items: center; padding: 15px; margin-bottom: 10px;
            background: #f8f9fa; border-radius: 8px; border-left: 4px solid #007bff;
        }}
        .step-item.success {{ border-left-color: #28a745; background: #d4edda; }}
        .step-item.error {{ border-left-color: #dc3545; background: #f8d7da; }}
        .step-icon {{ font-size: 1.5em; margin-right: 15px; }}
        .step-content {{ flex: 1; }}
        .step-title {{ font-weight: bold; font-size: 1.1em; margin-bottom: 5px; }}
        .step-message {{ color: #666; font-size: 0.9em; word-break: break-all; }}
        .step-duration {{ color: #999; font-size: 0.8em; }}
        .function-summary {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin-bottom: 30px; }}
        .function-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px; margin-top: 15px;
        }}
        .function-item {{
            display: flex; align-items: center; gap: 10px; padding: 15px;
            background: white; border-radius: 8px; border-left: 4px solid #007bff;
        }}
        .function-item.success {{ border-left-color: #28a745; }}
        .function-item.error {{ border-left-color: #dc3545; }}
        .function-icon {{ font-size: 1.5em; }}
        .overall-status {{ text-align: center; padding: 20px; }}
        .status-text {{ font-size: 1.8em; font-weight: bold; margin-top: 10px; }}
        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>小红书发布功能验证测试报告</h1>
            <div class="subtitle">CLI 版本 · Python + CloakBrowser</div>
        </div>

        <div class="content">
            <div class="summary-cards">
                <div class="card"><h3>总测试数</h3><div class="value">{report['totalTests']}</div></div>
                <div class="card success"><h3>通过</h3><div class="value">{report['passedTests']}</div></div>
                <div class="card {'success' if report['failedTests'] == 0 else 'error'}"><h3>失败</h3><div class="value">{report['failedTests']}</div></div>
                <div class="card {'success' if all_passed else 'error'}"><h3>成功率</h3><div class="value">{success_rate}%</div></div>
            </div>

            <div class="test-steps">
                <h2>📋 测试步骤详情</h2>
                {steps_html}
            </div>

            <div class="function-summary">
                <h2>📊 功能验证摘要</h2>
                <div class="function-grid">
                    {function_item('📝', '发布功能', summary['publishSuccess'])}
                    {function_item('🔍', '发布验证', summary['verifyPublishSuccess'])}
                    {function_item('🗑️', '删除功能', summary['deleteSuccess'])}
                    {function_item('🔍', '删除验证', summary['verifyDeleteSuccess'])}
                </div>
            </div>

            <div class="overall-status">
                <h2>🎯 整体状态</h2>
                <div class="status-text">{'✅ 所有功能正常' if all_passed else '❌ 存在问题'}</div>
            </div>
        </div>

        <div class="footer">
            <p>报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>小红书发布功能验证脚本 - CLI 版本</p>
        </div>
    </div>
</body>
</html>"""

    def print_report_summary(self, report: dict[str, Any]) -> None:
        print("\n" + "=" * 60)
        print("📊 小红书发布功能验证测试报告 (CLI版本)")
        print("=" * 60)
        print(f"📅 测试时间: {report['testDate']}")
        print(f"📈 总测试数: {report['totalTests']}")
        print(f"✅ 通过测试: {report['passedTests']}")
        print(f"❌ 失败测试: {report['failedTests']}")
        total = report["totalTests"] or 1
        print(f"📊 成功率: {report['passedTests'] / total * 100:.1f}%")

        print("\n📋 测试步骤详情:")
        for index, result in enumerate(report["results"], start=1):
            status = "✅" if result["success"] else "❌"
            duration = f" ({result['duration']}ms)" if result.get("duration") else ""
            print(f"  {index}. {status} {result['step']}: {result['message']}{duration}")
            if result.get("error"):
                print(f"     错误: {result['error']}")

        summary = report["summary"]
        print("\n📊 功能验证摘要:")
        print(f"  📝 发布功能: {'✅ 正常' if summary['publishSuccess'] else '❌ 异常'}")
        print(f"  🔍 发布验证: {'✅ 正常' if summary['verifyPublishSuccess'] else '❌ 异常'}")
        print(f"  🗑️ 删除功能: {'✅ 正常' if summary['deleteSuccess'] else '❌ 异常'}")
        print(f"  🔍 删除验证: {'✅ 正常' if summary['verifyDeleteSuccess'] else '❌ 异常'}")

        all_passed = all(summary.values())
        print(f"\n🎯 整体状态: {'✅ 所有功能正常' if all_passed else '❌ 存在问题'}")
        print("=" * 60)


def _now_ms() -> int:
    return int(time.time() * 1000)


def main() -> None:
    try:
        tester = CLIValidationTester()
        report = tester.run_validation_test()
        tester.save_report(report)
        tester.print_report_summary(report)
        sys.exit(0 if all(report["summary"].values()) else 1)
    except Exception as error:
        print(f"❌ 验证测试失败: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
