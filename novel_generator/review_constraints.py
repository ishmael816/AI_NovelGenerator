# novel_generator/review_constraints.py
# -*- coding: utf-8 -*-
"""Load review edits and annotations as generation constraints for the novel pipeline."""
import os
import json
from dataclasses import dataclass, field


@dataclass
class ReviewConstraints:
    replaced_content: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)

    def build_constraint_block(self) -> str:
        """Build the constraint text block for injection into chapter prompts."""
        if not self.constraints:
            return ""
        lines = ["", "【审阅约束 - 本章必须遵守】"]
        for i, c in enumerate(self.constraints, 1):
            priority = c.get("priority", "suggestion")
            section = c.get("section", "")
            text = c.get("constraint_text", "")
            prefix = "CRITICAL" if priority == "critical" else "SUGGESTION"
            lines.append(f"{i}. [{prefix}/{section}] {text}")
        return "\n".join(lines)

    def replace_in_architecture(self, arch_text: str) -> str:
        """Replace sections in architecture text with edited versions."""
        if not self.replaced_content:
            return arch_text
        result = arch_text
        for section_key, new_content in self.replaced_content.items():
            pattern = f"## {section_key}"
            if pattern in result:
                before = result.split(pattern, 1)[0]
                after_parts = result.split(pattern, 1)[1].split("## ", 1)
                if len(after_parts) > 1:
                    after = "## " + after_parts[1]
                else:
                    after = ""
                result = before + pattern + "\n" + new_content.strip() + "\n\n" + after
        return result


def load_review_constraints(outline_id: str, project_dir: str = None) -> ReviewConstraints:
    """Load edits and annotations for an outline, convert to generation constraints."""
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    review_dir = os.path.join(project_dir, "output", "review")
    constraints = ReviewConstraints()

    # Load edits
    edits_file = os.path.join(review_dir, "edits.json")
    if os.path.exists(edits_file):
        with open(edits_file, "r", encoding="utf-8") as f:
            all_edits = json.load(f)
        if outline_id in all_edits:
            constraints.replaced_content = dict(all_edits[outline_id])

    # Load annotations as constraints
    ann_file = os.path.join(review_dir, "annotations.json")
    if os.path.exists(ann_file):
        with open(ann_file, "r", encoding="utf-8") as f:
            all_annotations = json.load(f)
        for ann in all_annotations:
            if ann.get("outline_id") == outline_id:
                constraints.constraints.append({
                    "section": ann.get("section_key", ""),
                    "constraint_text": ann.get("text", ""),
                    "priority": ann.get("priority", "suggestion"),
                })
        # Sort: critical constraints first
        constraints.constraints.sort(key=lambda c: 0 if c.get("priority") == "critical" else 1)

    return constraints
