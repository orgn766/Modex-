"""Official workflow bootstrap with minimal provider routing.

The packaged Modex 1.7.3 workflow engine, routers, paper skills, and compile
skills are kept unchanged. Only the small provider adapters and isolated
post-skill adapters are loaded before importing ``main:app``. The former full
runner patch is still deliberately not imported: it changed skill prompts,
added ``--bare``, wrapped the scheduler, and installed checkpoint helpers that
could interfere with manuscript production.

Figure lifecycle wraps figure-related run_skill calls. Modeling-boundary wraps
only ``comp-modeling`` / ``comp-code`` and fail-closes on dual primary
objectives or orphan ledgers. Review-repair does not alter checkpoints; it
waits until a completed ``comp-review`` runner call and blocks the official
scheduler until its incremental repair contract passes. Modeling-boundary is
installed before review-repair so a repair modeling call still hits the gate.
"""
from services import runtime_config_patch
from services import preset_endpoint_patch
from services import figure_lifecycle_patch
from services import modeling_consistency_patch
from services import review_repair_patch

runtime_config_patch.install()
preset_endpoint_patch.install()
# Figure lifecycle is isolated from provider routing and review-repair logic.
# It wraps only figure-related run_skill calls.
figure_lifecycle_patch.install()
modeling_consistency_patch.install()
review_repair_patch.install()

from main import app  # noqa: E402  (load official app after adapters)
