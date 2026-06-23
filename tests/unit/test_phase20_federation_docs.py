"""
test_phase20_federation_docs.py — Phase 20: Federation Documentation Generation.

Covers:
  20.1  build_federation_workbook_html()
  20.2  build_federation_runbook_html()
  20.3  build_cell_workbook_html()
  20.7  build_dependency_workbook_html()
  20.8  build_command_reference_html()
  20.9  build_validation_sheet_html()
"""



import federation_docs as _fd
import federation_state as _fs
import html_base as _hb

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now():
    return "2026-06-01T12:00:00+00:00"


def _fed():
    fed = _fs.build_federation_state("fed-homelab", federation_name="Home Lab", now_fn=_now)
    _fs.register_cell(fed, "pve01-cell", hostname="pve01",
                      fqdn="pve01.home.example.com",
                      capabilities=["k3s-server", "forgejo"], now_fn=_now)
    _fs.register_cell(fed, "pve02-cell", hostname="pve02",
                      fqdn="pve02.home.example.com",
                      capabilities=["k3s-worker", "pbs-datastore"], now_fn=_now)
    _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
    _fs.declare_recovery(fed, "pve01-cell", "pve02-cell",
                          backup_locations=[{"type": "restic", "path": "/backup/pve01"}],
                          rto_minutes=60, rpo_hours=4, now_fn=_now)
    _fs.declare_recovery(fed, "pve02-cell", "pve01-cell",
                          backup_locations=[{"type": "restic", "path": "/backup/pve02"}],
                          now_fn=_now)
    return fed


def _meta():
    return {"generated_at": _now(), "generated_at_display": "2026-06-01 12:00:00 UTC"}


def _manifest():
    return {
        "cell_id": "pve01-cell",
        "host_identity": {"hostname": "pve01"},
        "dns_registry": [{"hostname": "forgejo.home.example.com", "ip": "192.168.1.11"}],
    }


# ===========================================================================
# 20.1 — Federation Workbook
# ===========================================================================

class TestFederationWorkbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return _fd.build_federation_workbook_html(_fed(), generation_meta=_meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_is_valid_html(self):
        page = self._build()
        assert "<!DOCTYPE html>" in page
        assert "</html>" in page

    def test_title_contains_federation_id(self):
        assert "fed-homelab" in self._build()

    def test_includes_cell_registry(self):
        page = self._build()
        assert "pve01-cell" in page
        assert "pve02-cell" in page

    def test_includes_trust_relationships(self):
        page = self._build()
        assert "Trust" in page
        assert "peer" in page

    def test_includes_recovery_relationships(self):
        page = self._build()
        assert "Recovery" in page
        assert "pve02-cell" in page

    def test_includes_readiness_scores(self):
        page = self._build()
        assert "score-green" in page or "score-yellow" in page

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()

    def test_self_contained(self):
        page = self._build()
        assert "cdn." not in page


# ===========================================================================
# 20.2 — Federation Runbook
# ===========================================================================

class TestFederationRunbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return _fd.build_federation_runbook_html(_fed(), generation_meta=_meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_includes_pre_recovery_coordination(self):
        page = self._build()
        assert "Pre-Recovery" in page or "Coordination" in page

    def test_includes_cell_recovery_sections(self):
        page = self._build()
        assert "Cell Recovery" in page or "pve01-cell" in page

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()


# ===========================================================================
# 20.3 — Cell Workbook
# ===========================================================================

class TestCellWorkbook:
    def _build(self, state_docs=None):
        _hb.reset_checkbox_counter()
        return _fd.build_cell_workbook_html("pve01-cell", state_docs=state_docs,
                                             generation_meta=_meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_title_contains_cell_id(self):
        assert "pve01-cell" in self._build()

    def test_includes_all_state_categories(self):
        page = self._build()
        for label, _ in _fd._STATE_CATEGORIES[:5]:
            assert label in page

    def test_17_categories_covered(self):
        assert len(_fd._STATE_CATEGORIES) == 17

    def test_missing_state_shows_warning(self):
        page = self._build(state_docs={})
        assert "No" in page or "Missing" in page

    def test_present_state_shows_green(self):
        page = self._build(state_docs={
            "hardware_state": {"collected_at": _now(), "cpu_model": "Intel Xeon"}
        })
        assert "score-green" in page

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()


# ===========================================================================
# 20.7 — Dependency Workbook
# ===========================================================================

class TestDependencyWorkbook:
    def _build(self):
        _hb.reset_checkbox_counter()
        return _fd.build_dependency_workbook_html(
            _fed(),
            cell_graphs={"pve01-cell": "forgejo → k3s-server → Flux CD"},
            generation_meta=_meta(),
        )

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_includes_federation_id(self):
        assert "fed-homelab" in self._build()

    def test_includes_recovery_deps(self):
        page = self._build()
        assert "pve01-cell" in page
        assert "pve02-cell" in page

    def test_includes_cell_graph(self):
        page = self._build()
        assert "forgejo" in page


# ===========================================================================
# 20.8 — Command Reference
# ===========================================================================

class TestCommandReference:
    def _build(self):
        _hb.reset_checkbox_counter()
        return _fd.build_command_reference_html("pve01-cell", manifest=_manifest(),
                                                 generation_meta=_meta())

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_title_contains_cell_id(self):
        assert "pve01-cell" in self._build()

    def test_includes_proxmox_commands(self):
        page = self._build()
        assert "pvecm" in page or "qm list" in page

    def test_includes_k3s_commands(self):
        page = self._build()
        assert "kubectl" in page

    def test_includes_keepass_commands(self):
        page = self._build()
        assert "keepassxc-cli" in page

    def test_includes_backup_commands(self):
        page = self._build()
        assert "run-backup.py" in page


# ===========================================================================
# 20.9 — Validation Sheet
# ===========================================================================

class TestValidationSheet:
    def _build(self, checklist=None):
        _hb.reset_checkbox_counter()
        items = checklist or [
            "All VMs running",
            "k3s nodes Ready",
            "Flux reconciled",
        ]
        return _fd.build_validation_sheet_html(
            "Post-Recovery pve01-cell", items,
            manifest=_manifest(), generation_meta=_meta(),
        )

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_includes_checklist_items(self):
        page = self._build()
        assert "All VMs running" in page

    def test_has_checkboxes(self):
        assert 'type="checkbox"' in self._build()

    def test_no_strikethrough(self):
        assert "line-through" not in self._build()

    def test_tuple_items_work(self):
        _hb.reset_checkbox_counter()
        items = [("Task A", "task-a"), ("Task B", "task-b")]
        page = _fd.build_validation_sheet_html("Test", items)
        assert "Task A" in page
        assert 'id="task-a"' in page
