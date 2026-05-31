#!/usr/bin/env python3
"""
template_registry.py — Template and base-image registry for doc-gen.

Provides TemplateRegistry: a wrapper around base_images and templates from
bootstrap-state.json that enables lookup of Proxmox VM templates and the
base ISO images they were built from.
"""

from typing import Optional


class TemplateRegistry:
    """
    Wrapper around base_images and templates lists for fast name-based lookups.

    Templates are keyed by name (str). Base images are keyed by name (str).
    template_for_vmid resolves which template a VM used via a vm_list that
    carries a template_name field per VM entry.
    """

    def __init__(self, base_images: list, templates: list):
        self._base_images = list(base_images or [])
        self._templates = list(templates or [])
        self._bi_by_name: dict[str, dict] = {
            bi["name"]: bi for bi in self._base_images if bi.get("name")
        }
        self._tmpl_by_name: dict[str, dict] = {
            t["name"]: t for t in self._templates if t.get("name")
        }

    def available(self) -> bool:
        return bool(self._base_images or self._templates)

    def base_image_count(self) -> int:
        return len(self._base_images)

    def template_count(self) -> int:
        return len(self._templates)

    def get_base_image(self, name: str) -> Optional[dict]:
        return self._bi_by_name.get(name)

    def get_template(self, name: str) -> Optional[dict]:
        return self._tmpl_by_name.get(name)

    def all_base_images(self) -> list:
        return list(self._base_images)

    def all_templates(self) -> list:
        return list(self._templates)

    def template_for_vmid(self, vmid, vm_list: list) -> Optional[dict]:
        """
        Look up the template used by a VM.

        vm_list entries are expected to carry a template_name field that
        maps to a template name in this registry.
        """
        try:
            target = int(vmid)
        except (TypeError, ValueError):
            return None
        for vm in vm_list:
            try:
                if int(vm.get("vmid", -1)) == target:
                    tmpl_name = vm.get("template_name")
                    if tmpl_name:
                        return self._tmpl_by_name.get(tmpl_name)
            except (TypeError, ValueError):
                continue
        return None


def build_template_registry(manifest: dict) -> "TemplateRegistry":
    """
    Build a TemplateRegistry from manifest["base_images"] and manifest["templates"].

    engine.py injects these keys from bootstrap-state.json.
    Returns an empty registry (available() == False) if both keys are absent.
    """
    base_images = manifest.get("base_images") or []
    templates = manifest.get("templates") or []
    return TemplateRegistry(base_images, templates)
