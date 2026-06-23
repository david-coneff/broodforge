"""
test_html_renderers.py — HTML runbooks and workbooks.

Covers:
  html_base.py:             html_page, h, p, pre, code, ul, ol, dl, table,
                            callout, divider, section, score_badge,
                            checkbox_item, checkbox_list
  html_recovery_runbook.py: build_recovery_runbook_html()
  html_bootstrap.py:        build_bootstrap_workbook_html(),
                            build_bootstrap_runbook_html()
  html_operational_report.py: build_operational_report_html()
  html_spawn_workbook.py:   build_spawn_workbook_html()

Universal checkbox behavior:
  - Checked state shows " done" in italics to the right
  - No strikethrough on label text
  - State persisted in localStorage via JS
  - These properties verified in CSS and JS of every HTML document
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import html_base as _hb
from html_bootstrap import build_bootstrap_runbook_html, build_bootstrap_workbook_html
from html_operational_report import build_operational_report_html
from html_recovery_runbook import build_recovery_runbook_html
from html_spawn_workbook import build_spawn_workbook_html

# ---------------------------------------------------------------------------
# Minimal stubs for graph/readiness
# ---------------------------------------------------------------------------

class _Node:
    def __init__(self, id_, label):
        self.id    = id_
        self.label = label
        self.vmid  = None

class _Edge:
    def __init__(self, src, tgt, edge_type="DEPENDS_ON"):
        self.source    = src
        self.target    = tgt
        self.edge_type = edge_type

class _Wave:
    def __init__(self, name, vms=None, mins=None):
        self.name               = name
        self.restore_order      = vms or []
        self.estimated_minutes  = mins
        self.prerequisites: list[str] = []

class _Graph:
    def __init__(self):
        self.restore_waves: list[_Wave] = []
        self.edges: list[_Edge]         = []
    def node_map(self) -> dict:
        return {}

class _Component:
    def __init__(self, id_, score, reason=""):
        self.component_id  = id_
        self.score         = score
        self.score_reason  = reason
        self.blocked_by    = None

class _Readiness:
    def __init__(self):
        self.overall_score        = "GREEN"
        self.overall_score_reason = "All components healthy"
        self.components: list[_Component] = []


def _manifest():
    return {
        "cell_id": "pve01-cell",
        "collected_at": "2026-06-01T12:00:00Z",
        "host": {"hostname": "pve01", "proxmox_version": "8.1"},
        "host_identity": {
            "hostname": "pve01", "domain": "home.example.com",
            "fqdn": "pve01.home.example.com",
        },
        "network_topology": {
            "profile": "wan",
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
            "wan_config": {"headscale_url": "https://pve01.home.example.com:8080"},
        },
        "storage_config": {
            "zfs_pool": {"pool_name": "rpool", "topology": "mirror"},
        },
        "vms": [{"vmid": 101, "name": "forgejo", "role": "gitops", "memory_mb": 2048, "cores": 2}],
        "k3s_cluster": {
            "pod_cidr": "10.42.0.0/16", "service_cidr": "10.43.0.0/16",
            "server_nodes": [{"hostname": "k3s-server-01"}],
            "worker_nodes": [],
        },
        "dns_registry": [{"hostname": "forgejo.home.example.com", "ip": "192.168.1.11",
                          "vmid": 101, "role": "gitops"}],
        "secret_registry": [
            {"id": "headscale-key", "name": "Headscale key",
             "keepass_path": "Infrastructure/headscale/api-key",
             "required_for_recovery": True},
        ],
        "external_dependencies": [],
        "provenance_records": [
            {"vmid": 101, "vm_name": "forgejo", "tofu_workspace": "vms/forgejo",
             "ansible_role": "forgejo", "source_commit": "abc1234"},
        ],
        "templates": [],
        "base_images": [{"name": "ubuntu-2204-base", "path": "/var/lib/vz/template/iso/ubuntu.iso"}],
        "external_backup": {"provider": "github", "github": {
            "repos": {"bootstrap": "https://github.com/example/bootstrap.git"},
        }},
        "backup_config": {"layers": {"secrets": {"destinations": [{"type": "local"}]}}},
        "service_contracts": [],
        "network_topology_declared": {
            "bridges": [{"name": "vmbr0", "address": "192.168.1.2/24", "vlan_aware": False, "ports": ["eno1"]}],
            "gateway": "192.168.1.1",
        },
    }


def _meta():
    return {"generated_at": "2026-06-01T12:00:00Z", "generated_at_display": "2026-06-01 12:00:00 UTC"}


def _graph():
    g = _Graph()
    n = _Node("forgejo", "forgejo")
    n.vmid = 101
    w = _Wave("Application VMs", [n], mins=15)
    g.restore_waves = [w]
    return g


def _readiness():
    r = _Readiness()
    r.components = [
        _Component("forgejo", "GREEN", "Service running"),
        _Component("k3s-server", "YELLOW", "Single server node"),
    ]
    return r


# ===========================================================================
# html_base — element builders
# ===========================================================================

class TestHtmlBase:
    def test_html_page_returns_string(self):
        page = _hb.html_page("Test", "<p>hello</p>")
        assert isinstance(page, str)

    def test_html_page_doctype(self):
        page = _hb.html_page("Test", "body")
        assert "<!DOCTYPE html>" in page

    def test_html_page_title_in_head(self):
        page = _hb.html_page("My Title", "body")
        assert "<title>My Title</title>" in page

    def test_html_page_title_in_header(self):
        page = _hb.html_page("My Title", "body")
        assert "<h1>My Title</h1>" in page

    def test_html_page_meta_shown(self):
        page = _hb.html_page("T", "body", meta="Generated: 2026-06-01")
        assert "Generated: 2026-06-01" in page

    def test_html_page_self_contained_no_external_urls(self):
        page = _hb.html_page("T", "body")
        # No CDN or external URLs in the CSS/JS
        assert "cdn." not in page
        assert "googleapis.com" not in page

    def test_heading(self):
        assert "<h2>" in _hb.h(2, "Section Title")

    def test_heading_escapes(self):
        assert "&lt;" in _hb.h(1, "<script>")

    def test_pre_escapes(self):
        assert "&lt;html&gt;" in _hb.pre("<html>")

    def test_code_escapes(self):
        assert "&amp;" in _hb.code("a & b")

    def test_ul(self):
        result = _hb.ul(["<b>item</b>"])
        assert "<ul>" in result
        assert "<li><b>item</b></li>" in result

    def test_table_headers(self):
        t = _hb.table(["A", "B"], [["x", "y"]])
        assert "<th>A</th>" in t
        assert "<th>B</th>" in t

    def test_dl(self):
        d = _hb.dl([("Key", "Value")])
        assert "<dt>Key</dt>" in d
        assert "<dd>Value</dd>" in d

    def test_callout_tip(self):
        c = _hb.callout("tip", "A tip")
        assert 'class="callout tip"' in c

    def test_callout_danger(self):
        c = _hb.callout("danger", "Danger!")
        assert 'class="callout danger"' in c

    def test_section_details(self):
        s = _hb.section("My Section", "<p>body</p>")
        assert "<details" in s
        assert "<summary>My Section</summary>" in s

    def test_section_open_by_default(self):
        s = _hb.section("S", "body", open_=True)
        assert "<details open>" in s or "open" in s

    def test_section_closed(self):
        s = _hb.section("S", "body", open_=False)
        assert "<details>" in s

    def test_score_badge_green(self):
        b = _hb.score_badge("GREEN")
        assert "score-green" in b
        assert "GREEN" in b

    def test_score_badge_red(self):
        b = _hb.score_badge("RED")
        assert "score-red" in b


# ===========================================================================
# Checkbox behavior (universal requirement)
# ===========================================================================

class TestCheckboxBehavior:
    def test_checkbox_item_has_input(self):
        item = _hb.checkbox_item("Do this task")
        assert '<input type="checkbox"' in item

    def test_checkbox_item_has_label(self):
        item = _hb.checkbox_item("Do this task")
        assert "<label" in item
        assert "Do this task" in item

    def test_checkbox_item_no_strikethrough_in_css(self):
        page = _hb.html_page("T", _hb.checkbox_item("item"))
        # CSS should NOT contain text-decoration: line-through on checked labels
        assert "line-through" not in page

    def test_checkbox_done_italic_in_css(self):
        # CSS must include font-style:italic for the done state
        page = _hb.html_page("T", _hb.checkbox_item("item"))
        assert "italic" in page
        assert "done" in page

    def test_checkbox_localStorage_in_js(self):
        page = _hb.html_page("T", _hb.checkbox_item("item"))
        assert "localStorage" in page

    def test_checkbox_done_after_content(self):
        # The done marker appears AFTER the label (to the right)
        page = _hb.html_page("T", _hb.checkbox_item("item"))
        assert "::after" in page or "content:" in page

    def test_checkbox_list(self):
        result = _hb.checkbox_list(["Task A", "Task B"])
        assert "Task A" in result
        assert "Task B" in result
        assert '<ul class="check-list">' in result

    def test_checkbox_item_id_set(self):
        item = _hb.checkbox_item("task", item_id="my-task")
        assert 'id="my-task"' in item

    def test_checkbox_checked_class_js(self):
        page = _hb.html_page("T", _hb.checkbox_item("x"))
        # JS should add 'checked' class (not 'done-class' or similar)
        assert "checked" in page

    def test_checkbox_universal_across_all_html_docs(self):
        # All HTML documents must include the checkbox CSS behavior
        # Test by checking the CSS is included in html_page
        page = _hb.html_page("Test", "<p>no checkboxes</p>")
        # Even pages with no checkboxes include the CSS for consistency
        assert "check-item" in page
        assert "font-style:italic" in page or "font-style: italic" in page


# ===========================================================================
# HTML Recovery Runbook
# ===========================================================================

class TestHtmlRecoveryRunbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return build_recovery_runbook_html(_manifest(), _graph(), _readiness(), _meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_is_valid_html(self):
        page = self._build()
        assert "<!DOCTYPE html>" in page
        assert "</html>" in page

    def test_title_contains_cell_id(self):
        page = self._build()
        assert "pve01-cell" in page

    def test_includes_readiness_score(self):
        page = self._build()
        assert "GREEN" in page or "score-green" in page

    def test_includes_pre_recovery_checklist(self):
        page = self._build()
        assert "Pre-Recovery" in page

    def test_includes_wave_0_network(self):
        page = self._build()
        assert "Wave 0" in page
        assert "Network" in page

    def test_includes_restore_waves(self):
        page = self._build()
        assert "Wave 1" in page or "Application VMs" in page

    def test_includes_appendix_a(self):
        page = self._build()
        assert "Appendix A" in page

    def test_includes_appendix_d_secrets(self):
        page = self._build()
        assert "Appendix D" in page

    def test_includes_appendix_g_ext_deps(self):
        page = self._build()
        assert "Appendix G" in page

    def test_checkboxes_present(self):
        page = self._build()
        assert 'type="checkbox"' in page

    def test_no_strikethrough(self):
        page = self._build()
        assert "line-through" not in page

    def test_done_italic(self):
        page = self._build()
        assert "italic" in page
        assert "done" in page

    def test_self_contained(self):
        page = self._build()
        assert "cdn." not in page
        assert "src=" not in page.lower().split("<script")[0]


# ===========================================================================
# HTML Recovery Runbook — Appendix I OS Variant Migration (9.T.12)
# ===========================================================================

_MIGRATION_SUCCESS = {
    "migration_id": "mig-html-001",
    "node_vm_name": "k3s-server-01",
    "from_variant": "ubuntu",
    "to_variant": "talos",
    "started_at": "2026-06-01T10:00:00Z",
    "completed_at": "2026-06-01T10:15:00Z",
    "outcome": "success",
    "snapshot_vmid": 9501,
    "dry_run": False,
    "error": None,
}

_MIGRATION_FAILED = {
    "migration_id": "mig-html-002",
    "node_vm_name": "k3s-server-02",
    "from_variant": "talos",
    "to_variant": "ubuntu",
    "started_at": "2026-06-02T08:00:00Z",
    "completed_at": None,
    "outcome": "failed",
    "snapshot_vmid": None,
    "dry_run": False,
    "error": "talosctl apply-config timed out",
}


class TestHtmlRecoveryRunbookOsMigration:
    def _build(self, history=None):
        _hb.reset_checkbox_counter()
        m = _manifest()
        if history is not None:
            m["migration_history"] = history
        return build_recovery_runbook_html(m, _graph(), _readiness(), _meta())

    def test_appendix_i_absent_when_no_history(self):
        page = self._build()
        assert "Appendix I" not in page

    def test_appendix_i_absent_when_empty_history(self):
        page = self._build(history=[])
        assert "Appendix I" not in page

    def test_appendix_i_present_with_history(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "Appendix I" in page
        assert "OS Variant Migration" in page

    def test_node_name_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "k3s-server-01" in page

    def test_variant_direction_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "ubuntu" in page
        assert "talos" in page

    def test_success_outcome_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "SUCCESS" in page

    def test_snapshot_vmid_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "9501" in page

    def test_error_shown_for_failed(self):
        page = self._build(history=[_MIGRATION_FAILED])
        assert "talosctl apply-config timed out" in page

    def test_rollback_commands_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "qm rollback" in page

    def test_multiple_records_both_shown(self):
        page = self._build(history=[_MIGRATION_SUCCESS, _MIGRATION_FAILED])
        assert "k3s-server-01" in page
        assert "k3s-server-02" in page

    def test_dry_run_flag_shown(self):
        dry = dict(_MIGRATION_SUCCESS, dry_run=True)
        page = self._build(history=[dry])
        assert "DRY RUN" in page

    def test_talos_alternative_md_link(self):
        page = self._build(history=[_MIGRATION_SUCCESS])
        assert "TALOS-ALTERNATIVE" in page


# ===========================================================================
# HTML Bootstrap Workbook
# ===========================================================================

class TestHtmlBootstrapWorkbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return build_bootstrap_workbook_html(_manifest(), _meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_title_contains_cell_id(self):
        page = self._build()
        assert "pve01-cell" in page

    def test_includes_vm_inventory(self):
        page = self._build()
        assert "forgejo" in page

    def test_includes_network(self):
        page = self._build()
        assert "192.168.1.0/24" in page

    def test_includes_stage_03(self):
        page = self._build()
        assert "Stage 03" in page

    def test_has_checkboxes(self):
        page = self._build()
        assert 'type="checkbox"' in page

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()


# ===========================================================================
# HTML Bootstrap Runbook
# ===========================================================================

class TestHtmlBootstrapRunbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return build_bootstrap_runbook_html(_manifest(), _meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_includes_all_stages(self):
        page = self._build()
        for stage in ["Stage 01", "Stage 02", "Stage 03", "Stage 04",
                      "Stage 05", "Stage 06", "Stage 07", "Stage 08"]:
            assert stage in page, f"Missing {stage}"

    def test_includes_forge_steps(self):
        page = self._build()
        assert "forge.sh" in page or "forge" in page.lower()

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()


# ===========================================================================
# HTML Operational Report
# ===========================================================================

class TestHtmlOperationalReport:
    def _build(self):
        _hb.reset_checkbox_counter()
        return build_operational_report_html(_manifest(), _readiness(), _meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_includes_readiness_section(self):
        page = self._build()
        assert "Overall Readiness" in page

    def test_includes_secret_completeness(self):
        page = self._build()
        assert "Secret" in page

    def test_score_badges_present(self):
        page = self._build()
        assert "score-green" in page or "score-yellow" in page

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()


# ===========================================================================
# HTML Spawn Workbook
# ===========================================================================

class TestHtmlSpawnWorkbook:
    def _plan(self):
        return {
            "package_id":   "spawn-pve01-broodling01-2026-06-01",
            "cell_id":      "pve01-cell",
            "hostname":     "broodling01",
            "network_mode": "lan",
            "generated_at": "2026-06-01T12:00:00Z",
            "disposition":  {"execution_mode": "autonomous", "services": ["k3s-worker"]},
            "vms":          [{"vmid": 201, "name": "k3s-worker-01", "lan_ip": "192.168.1.21"}],
        }

    def _manifest(self):
        return {
            "cell_id": "pve01-cell",
            "proxmox_cluster": {"address": "192.168.1.2"},
        }

    def _hw(self):
        return {
            "ram_gb": 32,
            "disks": [{"id": "/dev/sda", "size_gb": 500}],
            "nics":  [{"name": "eno1", "mac": "aa:bb:cc:dd:ee:ff"}],
        }

    def _build(self):
        _hb.reset_checkbox_counter()
        return build_spawn_workbook_html(self._plan(), self._manifest(), self._hw())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_title_contains_hostname(self):
        page = self._build()
        assert "broodling01" in page

    def test_includes_all_phases(self):
        page = self._build()
        for phase in ["Phase 00", "Phase 01", "Phase 02", "Phase 03", "Phase 04"]:
            assert phase in page, f"Missing {phase}"

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()

    def test_hardware_profile_shown(self):
        page = self._build()
        assert "/dev/sda" in page or "sda" in page


# ===========================================================================
# HTML Recovery Workbook (I1 — missing tests)
# ===========================================================================

class TestHtmlRecoveryWorkbook:
    def _build(self):
        from dependencies import build_graph
        from html_recovery_workbook import build_recovery_workbook_html
        from readiness import score_graph
        _hb.reset_checkbox_counter()
        m = _manifest()
        g = build_graph(m)
        r = score_graph(g, m)
        return build_recovery_workbook_html(m, g, r, _meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_is_valid_html(self):
        page = self._build()
        assert "<!DOCTYPE html>" in page
        assert "</html>" in page

    def test_hostname_in_page(self):
        page = self._build()
        assert "pve01" in page

    def test_overall_readiness_score(self):
        page = self._build()
        assert "GREEN" in page or "score-green" in page

    def test_restore_sequence_section(self):
        page = self._build()
        assert "Restore Sequence" in page or "Wave" in page

    def test_recovery_readiness_section(self):
        page = self._build()
        assert "Readiness" in page

    def test_checkboxes_present(self):
        page = self._build()
        assert 'type="checkbox"' in page

    def test_self_contained(self):
        page = self._build()
        assert "cdn." not in page


# ===========================================================================
# HTML Forge Workbook (I1 — missing tests)
# ===========================================================================

class TestHtmlForgeWorkbook:
    def _build(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "html_forge_workbook",
            os.path.join(_ROOT, "proxmox-bootstrap", "html_forge_workbook.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _hb.reset_checkbox_counter()
        return mod.build_forge_workbook_html(_manifest())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_is_valid_html(self):
        page = self._build()
        assert "<!DOCTYPE html>" in page and "</html>" in page

    def test_self_contained(self):
        assert "cdn." not in self._build()

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()


# ===========================================================================
# HTML Phoenix Workbook (I1 — missing tests)
# ===========================================================================

class TestHtmlPhoenixWorkbook:
    def _build(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "html_phoenix_workbook",
            os.path.join(_ROOT, "proxmox-bootstrap", "html_phoenix_workbook.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _hb.reset_checkbox_counter()
        return mod.build_phoenix_workbook_html({})

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_is_valid_html(self):
        page = self._build()
        assert "<!DOCTYPE html>" in page and "</html>" in page

    def test_self_contained(self):
        assert "cdn." not in self._build()

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()
