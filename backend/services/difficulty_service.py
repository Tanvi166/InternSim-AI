"""
Adaptive Difficulty Engine for InternSim AI.

Defines the mathematical policy, constants, and helper functions for computing
rolling ticket performance and updating user difficulty tiers.

Policy Specifications:
- Difficulty tiers range from MIN_DIFFICULTY_TIER (1) to MAX_DIFFICULTY_TIER (5).
- A ticket is deemed ELIGIBLE for difficulty evaluation only if it is passed
  (correctness_score >= MIN_PASSING_CORRECTNESS_SCORE, default 40/60).
- Multiple submissions for the same ticket are deduplicated: only the latest
  submission for each distinct ticket is considered.
- Rolling window requires ROLLING_WINDOW_SIZE (3) distinct eligible tickets.
- If fewer than 3 distinct eligible tickets exist, difficulty remains UNCHANGED ('insufficient_data').
- PROMOTION: Rolling average >= PROMOTION_THRESHOLD (75.0/100) -> tier + 1 (capped at 5).
- DEMOTION: Rolling average < DEMOTION_THRESHOLD (50.0/100) -> tier - 1 (floored at 1).
  A buffer zone between 50.0 and 74.9 keeps difficulty stable ('unchanged') to prevent oscillation.
"""

from typing import List, Dict, Any, Optional, Tuple

MIN_DIFFICULTY_TIER = 1
MAX_DIFFICULTY_TIER = 5
MIN_PASSING_CORRECTNESS_SCORE = 40
ROLLING_WINDOW_SIZE = 3
PROMOTION_THRESHOLD = 75.0
DEMOTION_THRESHOLD = 50.0

def get_distinct_eligible_submissions(submissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extracts distinct passed tickets sorted from newest to oldest.
    If a ticket has multiple submission attempts, only the most recent submission is used.
    Submissions that failed correctness (< 40) are excluded from difficulty tiering.
    """
    # Sort chronologically descending if created_at exists, else preserve received order
    sorted_subs = sorted(
        submissions,
        key=lambda s: s.get("created_at", ""),
        reverse=True
    )

    seen_task_ids = set()
    eligible = []

    for sub in sorted_subs:
        task_id = sub.get("task_id")
        if not task_id or task_id in seen_task_ids:
            continue
        
        # Only passed tickets count towards difficulty evaluation
        correctness = sub.get("correctness_score", 0) or 0
        if correctness >= MIN_PASSING_CORRECTNESS_SCORE:
            seen_task_ids.add(task_id)
            eligible.append(sub)

    return eligible

def calculate_rolling_difficulty_decision(
    current_tier: int,
    distinct_eligible_subs: List[Dict[str, Any]]
) -> Tuple[int, Optional[float], str, str]:
    """
    Computes tier update decision based on the latest 3 distinct eligible tickets.

    Returns:
        (new_tier, rolling_average, decision_action, rationale)
        decision_action: 'promoted' | 'demoted' | 'unchanged' | 'insufficient_data'
    """
    # Clamp current tier to valid bounds
    clamped_current = max(MIN_DIFFICULTY_TIER, min(current_tier, MAX_DIFFICULTY_TIER))

    if len(distinct_eligible_subs) < ROLLING_WINDOW_SIZE:
        return (
            clamped_current,
            None,
            "insufficient_data",
            f"Need {ROLLING_WINDOW_SIZE} distinct completed tickets to evaluate tier progression (currently have {len(distinct_eligible_subs)})."
        )

    # Consider the 3 most recent distinct tickets
    window = distinct_eligible_subs[:ROLLING_WINDOW_SIZE]
    total_scores = [sub.get("total_score", 0) or 0 for sub in window]
    rolling_avg = sum(total_scores) / len(total_scores)

    if rolling_avg >= PROMOTION_THRESHOLD:
        if clamped_current >= MAX_DIFFICULTY_TIER:
            return (
                MAX_DIFFICULTY_TIER,
                rolling_avg,
                "unchanged",
                f"Rolling average is {rolling_avg:.1f}/100 (>= {PROMOTION_THRESHOLD}), but user is already at maximum Tier {MAX_DIFFICULTY_TIER}."
            )
        return (
            clamped_current + 1,
            rolling_avg,
            "promoted",
            f"Promoted to Tier {clamped_current + 1}: Rolling average across last 3 tickets is {rolling_avg:.1f}/100 (>= {PROMOTION_THRESHOLD})."
        )
    elif rolling_avg < DEMOTION_THRESHOLD:
        if clamped_current <= MIN_DIFFICULTY_TIER:
            return (
                MIN_DIFFICULTY_TIER,
                rolling_avg,
                "unchanged",
                f"Rolling average is {rolling_avg:.1f}/100 (< {DEMOTION_THRESHOLD}), but user is already at base Tier {MIN_DIFFICULTY_TIER}."
            )
        return (
            clamped_current - 1,
            rolling_avg,
            "demoted",
            f"Adjusted to Tier {clamped_current - 1}: Rolling average across last 3 tickets dropped to {rolling_avg:.1f}/100 (< {DEMOTION_THRESHOLD})."
        )
    else:
        return (
            clamped_current,
            rolling_avg,
            "unchanged",
            f"Tier {clamped_current} maintained: Rolling average is {rolling_avg:.1f}/100 (stable within {DEMOTION_THRESHOLD}-{PROMOTION_THRESHOLD} range)."
        )

def evaluate_and_update_user_difficulty(supabase_client, user_id: str) -> Dict[str, Any]:
    """
    Queries user profile and all submissions, runs the adaptive difficulty engine,
    and updates profiles.current_difficulty_tier if changed.
    Returns audit details for logging or analytics.
    """
    profile_res = supabase_client.table("profiles").select("current_difficulty_tier").eq("id", user_id).single().execute()
    current_tier = profile_res.data.get("current_difficulty_tier", 1) if profile_res.data else 1

    subs_res = (
        supabase_client.table("submissions")
        .select("submission_id, task_id, total_score, correctness_score, quality_score, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    submissions = subs_res.data or []

    distinct_eligible = get_distinct_eligible_submissions(submissions)
    new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(current_tier, distinct_eligible)

    if new_tier != current_tier:
        supabase_client.table("profiles").update({"current_difficulty_tier": new_tier}).eq("id", user_id).execute()

    return {
        "user_id": user_id,
        "previous_tier": current_tier,
        "new_tier": new_tier,
        "rolling_average": rolling_avg,
        "action": action,
        "rationale": rationale,
        "distinct_eligible_count": len(distinct_eligible)
    }
