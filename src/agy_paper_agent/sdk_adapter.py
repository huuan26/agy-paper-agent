"""Google Antigravity Python SDK (`google.antigravity`) adapter and pipeline runner (D-01)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agy_paper_agent.bundle import (
    REPO_ROOT,
    audit_bundle_prose,
    inspect_bundle,
    verify_paper_bundle,
)
from agy_paper_agent.contracts import (
    OutlineContract,
    ReviewerCritique,
    RevisionDecision,
    SymbolTable,
)
from agy_paper_agent.sdk_tools import (
    RunTelemetryReport,
    SDKBackendProtocol,
    SDKBudgetSettings,
    StageTelemetry,
    build_sdk_custom_tools,
)


def _is_raster_subagent(args: dict[str, Any]) -> bool:
    target = str(args.get("TypeName") or args.get("name") or "").strip().lower()
    return target == "image-generator"


class GoogleAntigravityBackend:
    """Production adapter wrapping `google.antigravity.Agent` and `LocalAgentConfig`."""

    def __init__(
        self,
        *,
        plugin_root: Path = REPO_ROOT,
        budget: SDKBudgetSettings | None = None,
        api_key: str | None = None,
        vertex: bool = False,
        project: str | None = None,
        location: str | None = None,
        cutoff_date: str | None = None,
    ) -> None:
        self.plugin_root = plugin_root
        self.budget = budget or SDKBudgetSettings()
        self.api_key = api_key
        self.vertex = vertex
        self.project = project
        self.location = location
        self.cutoff_date = cutoff_date

    def build_agent_config(
        self,
        *,
        bundle_dir: Path,
        auto_approve: bool,
        response_schema: type[BaseModel] | None = None,
        model: str | None = None,
    ) -> Any:
        """Construct an official `google.antigravity.LocalAgentConfig` instance."""
        try:
            from google.antigravity import LocalAgentConfig, types
            from google.antigravity.hooks import policy
        except ImportError as exc:
            raise RuntimeError(
                "Package 'google-antigravity' is required for live SDK execution. "
                'Install via `.\\.venv\\Scripts\\python.exe -m pip install -e ".[sdk]"`.'
            ) from exc

        rules_text = (self.plugin_root / "rules" / "AGENTS.md").read_text(encoding="utf-8")
        behavior = (
            types.AgentBehavior.AUTONOMOUS if auto_approve else types.AgentBehavior.INTERACTIVE
        )
        policies = [
            policy.deny("invoke_subagent", when=_is_raster_subagent, name="deny_raster_invoke"),
            policy.deny("start_subagent", when=_is_raster_subagent, name="deny_raster_start"),
            policy.allow_all(),
        ]
        cfg_kwargs: dict[str, Any] = {
            "system_instructions": rules_text,
            "skills_paths": [str(self.plugin_root / "skills")],
            "workspaces": [str(bundle_dir.resolve())],
            "tools": build_sdk_custom_tools(bundle_dir, cutoff_date=self.cutoff_date),
            "policies": policies,
            "capabilities": types.CapabilitiesConfig(agent_behavior=behavior),
            "budget_config": types.BudgetConfig(
                max_model_calls=self.budget.max_model_calls,
                max_tool_calls=self.budget.max_tool_calls,
                max_input_tokens=self.budget.max_input_tokens,
                max_output_tokens=self.budget.max_output_tokens,
                max_total_tokens=self.budget.max_total_tokens,
            ),
        }
        if model is not None:
            cfg_kwargs["model"] = model
        if response_schema is not None:
            cfg_kwargs["response_schema"] = response_schema
        if self.api_key:
            cfg_kwargs["api_key"] = self.api_key
        if self.vertex:
            cfg_kwargs["vertex"] = True
            if self.project:
                cfg_kwargs["project"] = self.project
            if self.location:
                cfg_kwargs["location"] = self.location
        return LocalAgentConfig(**cfg_kwargs)

    async def run_turn(
        self,
        prompt: str,
        *,
        stage_name: str,
        bundle_dir: Path,
        auto_approve: bool,
        response_schema: type[BaseModel] | None = None,
        model: str | None = None,
    ) -> tuple[Any, StageTelemetry]:
        from google.antigravity import Agent

        config = self.build_agent_config(
            bundle_dir=bundle_dir,
            auto_approve=auto_approve,
            response_schema=response_schema,
            model=model,
        )
        t0 = time.perf_counter()
        async with Agent(config=config) as agent:
            response = await agent.chat(prompt)
            output = (
                await response.structured_output()
                if response_schema is not None
                else await response.text()
            )
            usage = getattr(agent.conversation, "total_usage", None)
            stop_reason = str(getattr(response, "stop_reason", "UNSPECIFIED"))
        elapsed = time.perf_counter() - t0
        telemetry = StageTelemetry(
            stage=stage_name,
            wall_clock_sec=round(elapsed, 3),
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            cached_tokens=int(getattr(usage, "cached_content_token_count", 0) or 0),
            candidates_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            thoughts_tokens=int(getattr(usage, "thoughts_token_count", 0) or 0),
            total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
            stop_reason=stop_reason,
        )
        return output, telemetry


class SDKPaperCoAuthorRunner:
    """Orchestrates interactive single-stage or autonomous batch runs over `SDKBackendProtocol`."""

    def __init__(self, backend: SDKBackendProtocol) -> None:
        self.backend = backend

    async def run_pipeline(
        self,
        bundle_dir: Path,
        *,
        stage: str = "stage1_outline",
        auto_approve: bool = False,
        force_ingest: bool = False,
        hitl_notes: list[str] | None = None,
        pro_model: str | None = None,
        flash_model: str | None = None,
    ) -> dict[str, Any]:
        if stage == "all" and not auto_approve:
            raise ValueError("stage='all' requires auto_approve=True (D-03 Interactive Co-Author).")

        stages = (
            [
                "stage0_ingest",
                "stage1_outline",
                "stage2_literature",
                "stage3_visuals",
                "stage4_sections",
                "stage5_refinement",
            ]
            if stage == "all"
            else [stage]
        )
        telemetry_report = RunTelemetryReport(bundle_dir=str(bundle_dir), auto_approve=auto_approve)
        results: dict[str, Any] = {"completed_stages": []}

        if "stage0_ingest" in stages:
            st = inspect_bundle(bundle_dir)
            if st.has_canonical_contract and not force_ingest:
                results["stage0"] = {"bypassed": True}
            else:
                sym_out, tel = await self.backend.run_turn(
                    f"Execute paper-ingestion skill for '{bundle_dir}' and return SymbolTable.",
                    stage_name="stage0_ingest",
                    bundle_dir=bundle_dir,
                    auto_approve=auto_approve,
                    response_schema=SymbolTable,
                    model=pro_model,
                )
                telemetry_report.stages.append(tel)
                sym_model = SymbolTable.model_validate(sym_out)
                (bundle_dir / "contract" / "symbol_table.json").write_text(
                    json.dumps(sym_model.model_dump(), indent=2) + "\n", encoding="utf-8"
                )
                results["stage0"] = {"bypassed": False, "symbols": len(sym_model.entries)}
            results["completed_stages"].append("stage0_ingest")

        if "stage1_outline" in stages:
            out_dict, tel = await self.backend.run_turn(
                f"Synthesize canonical OutlineContract for '{bundle_dir}'.",
                stage_name="stage1_outline",
                bundle_dir=bundle_dir,
                auto_approve=auto_approve,
                response_schema=OutlineContract,
                model=pro_model,
            )
            telemetry_report.stages.append(tel)
            validated_outline = OutlineContract.model_validate(out_dict)
            (bundle_dir / "state" / "outline.json").write_text(
                json.dumps(validated_outline.model_dump(), indent=2) + "\n", encoding="utf-8"
            )
            results["completed_stages"].append("stage1_outline")

        if "stage2_literature" in stages:
            _, tel = await self.backend.run_turn(
                f"Execute paper-lit-verify skill in '{bundle_dir}'.",
                stage_name="stage2_literature",
                bundle_dir=bundle_dir,
                auto_approve=auto_approve,
                model=flash_model,
            )
            telemetry_report.stages.append(tel)
            results["completed_stages"].append("stage2_literature")

        if "stage3_visuals" in stages:
            _, tel = await self.backend.run_turn(
                f"Execute paper-vector-viz skill in '{bundle_dir}'.",
                stage_name="stage3_visuals",
                bundle_dir=bundle_dir,
                auto_approve=auto_approve,
                model=pro_model,
            )
            telemetry_report.stages.append(tel)
            results["completed_stages"].append("stage3_visuals")

        if "stage4_sections" in stages:
            _, tel = await self.backend.run_turn(
                f"Draft remaining sections in '{bundle_dir}/manuscript/main.tex'.",
                stage_name="stage4_sections",
                bundle_dir=bundle_dir,
                auto_approve=auto_approve,
                model=pro_model,
            )
            telemetry_report.stages.append(tel)
            suite4 = verify_paper_bundle(bundle_dir)
            if not suite4.all_passed:
                raise RuntimeError(f"Stage 4 failed deterministic gates: {suite4.model_dump()}")
            results["completed_stages"].append("stage4_sections")

        if "stage5_refinement" in stages:
            pre_prose = audit_bundle_prose(
                bundle_dir,
                report_out=bundle_dir / "state" / "verification_reports" / "stage5_prose_pre.json",
            )
            reviews: list[dict[str, Any]] = []
            for role, mdl in (
                ("math_methodology", pro_model),
                ("empirical_evidence", pro_model),
                ("vlm_venue_layout", flash_model),
                ("prose_style", pro_model),
            ):
                extra_ctx = (
                    f" Detector report: {json.dumps(pre_prose.to_dict())}."
                    if role == "prose_style"
                    else ""
                )
                crit_raw, tel = await self.backend.run_turn(
                    f"Critique '{bundle_dir}/manuscript/main.tex' as '{role}'.{extra_ctx}",
                    stage_name=f"stage5_critic_{role}",
                    bundle_dir=bundle_dir,
                    auto_approve=auto_approve,
                    response_schema=ReviewerCritique,
                    model=mdl,
                )
                telemetry_report.stages.append(tel)
                reviews.append(ReviewerCritique.model_validate(crit_raw).model_dump())

            manuscript_dir = bundle_dir / "manuscript"
            backup_dir = bundle_dir / "state" / "_sdk_rollback_snapshot"
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(manuscript_dir, backup_dir)

            _, rev_tel = await self.backend.run_turn(
                f"Revise '{manuscript_dir}/main.tex' addressing {json.dumps(reviews)} "
                f"and hitl_notes={json.dumps(hitl_notes or [])}.",
                stage_name="stage5_revision",
                bundle_dir=bundle_dir,
                auto_approve=auto_approve,
                model=pro_model,
            )
            telemetry_report.stages.append(rev_tel)

            suite5 = verify_paper_bundle(bundle_dir)
            post_prose = audit_bundle_prose(
                bundle_dir,
                report_out=bundle_dir / "state" / "verification_reports" / "stage5_prose_post.json",
            )
            if suite5.all_passed and post_prose.critical_issues == 0:
                outcome = "accept" if auto_approve else "await_hitl"
            else:
                shutil.rmtree(manuscript_dir)
                shutil.copytree(backup_dir, manuscript_dir)
                outcome = "rollback"

            decision = RevisionDecision.model_validate(
                {
                    "iteration": 1,
                    "gates": suite5.model_dump(),
                    "reviews": reviews,
                    "prose_audit": {
                        "engine_mode": post_prose.engine_mode,
                        "pre_issues": pre_prose.total_issues,
                        "post_issues": post_prose.total_issues,
                        "critical_issues": post_prose.critical_issues,
                        "passed": post_prose.passed,
                    },
                    "hitl_notes": hitl_notes or [],
                    "addressed_issues": ["Applied SDK Stage 5 revision"],
                    "outcome": outcome,
                }
            )
            (bundle_dir / "state" / "refinement_worklog.json").write_text(
                json.dumps(decision.model_dump(), indent=2) + "\n", encoding="utf-8"
            )
            results["stage5"] = {"outcome": outcome, "all_passed": suite5.all_passed}
            results["completed_stages"].append("stage5_refinement")

        tel_dict = telemetry_report.to_dict()
        (bundle_dir / "state" / "sdk_telemetry.json").write_text(
            json.dumps(tel_dict, indent=2) + "\n", encoding="utf-8"
        )
        results["telemetry"] = tel_dict["totals"]
        return results


__all__ = [
    "GoogleAntigravityBackend",
    "RunTelemetryReport",
    "SDKBackendProtocol",
    "SDKBudgetSettings",
    "SDKPaperCoAuthorRunner",
    "StageTelemetry",
    "build_sdk_custom_tools",
]
