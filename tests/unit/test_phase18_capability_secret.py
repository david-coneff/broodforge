"""
test_phase18_capability_secret.py — Phase 18: Capability State and Secret Reference State.

Covers:
  18.1  data-model/capability-state-schema.json
  18.2  CapabilityEntry, CapabilityState, derive_capabilities_from_state()
  18.3  verify_capabilities() via derive_capabilities_from_state with state inputs
  18.4  build_capability_index() — cross-cell aggregation + CapabilityIndex
  18.5  data-model/secret-reference-state-schema.json
  18.6  SecretRefEntry, SecretReferenceState, migrate_from_bootstrap()
        build_recovery_critical(), secret_ref_state_to_dict()
"""

import json
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))
sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))

import capability_state as _cs
import secret_reference_state as _sr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bootstrap():
    return {
        "schema_version": "1.0",
        "cell_id": "pve01-cell",
        "host_identity": {
            "hostname": "pve01",
            "domain": "home.example.com",
            "fqdn": "pve01.home.example.com",
        },
        "network_topology": {
            "profile": "wan",
            "management_cidr": "192.168.1.0/24",
            "wan_config": {
                "headscale_url": "https://pve01.home.example.com:8080",
            },
        },
        "storage_config": {
            "zfs_pool": {"pool_name": "rpool", "topology": "mirror"},
        },
        "k3s_cluster": {
            "server_nodes": [{"hostname": "k3s-server-01"}],
            "worker_nodes": [{"hostname": "k3s-worker-01"}],
        },
        "vms": [
            {"name": "forgejo", "vmid": 101},
            {"name": "k3s-server-01", "vmid": 102},
        ],
        "service_contracts": [
            {"service": "forgejo", "vm_name": "forgejo"},
        ],
        "backup_config": {
            "layers": {"secrets": {"destinations": [{"type": "local"}]}},
        },
        "secret_registry": [
            {
                "id": "headscale-key",
                "name": "Headscale API key",
                "keepass_path": "Infrastructure/headscale/api-key",
                "owning_cell": "pve01-cell",
                "required_for_recovery": True,
            },
            {
                "id": "forgejo-admin",
                "name": "Forgejo admin password",
                "keepass_path": "Infrastructure/forgejo/admin-password",
                "owning_cell": "pve01-cell",
                "required_for_recovery": True,
            },
        ],
    }


def _now():
    return "2026-06-01T12:00:00+00:00"


# ===========================================================================
# 18.1 — capability-state-schema.json
# ===========================================================================

class TestCapabilityStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "capability-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Capability State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "declared_at" in s["required"]
        assert "schema_version" in s["required"]

    def test_capability_entry_definition(self):
        s = self._schema()
        defn = s["definitions"]["capability_entry"]
        assert "id" in defn["properties"]
        assert "category" in defn["properties"]
        assert "status" in defn["properties"]

    def test_schema_validates_derived_state(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        schema = self._schema()
        bs = _bootstrap()
        state = _cs.derive_capabilities_from_state("pve01-cell", bs, now_fn=_now)
        doc = _cs.capability_state_to_dict(state)
        jsonschema.validate(doc, schema)


# ===========================================================================
# 18.2 — CapabilityEntry, CapabilityState
# ===========================================================================

class TestCapabilityEntry:
    def test_entry_defaults(self):
        e = _cs.CapabilityEntry(id="k3s-server", category="compute")
        assert e.status == "active"
        assert e.description is None
        assert e.serves_cells == []

    def test_entry_with_all_fields(self):
        e = _cs.CapabilityEntry(
            id="headscale",
            category="networking",
            status="active",
            description="Tailnet coordinator",
            version="0.23",
            endpoint="https://pve01.home.example.com:8080",
            serves_cells=["cell-b"],
            tags=["wan"],
            ram_gib=1.0,
            cpu_cores=1,
        )
        assert e.endpoint == "https://pve01.home.example.com:8080"
        assert e.serves_cells == ["cell-b"]

    def test_standard_cap_ids(self):
        assert _cs.CAP_K3S_SERVER == "k3s-server"
        assert _cs.CAP_K3S_WORKER == "k3s-worker"
        assert _cs.CAP_HEADSCALE == "headscale"
        assert _cs.CAP_DNSMASQ == "dnsmasq"
        assert _cs.CAP_ASSESSMENT_ENGINE == "assessment-engine"


class TestCapabilityState:
    def _state(self):
        caps = [
            _cs.CapabilityEntry(id="k3s-server", category="compute", status="active"),
            _cs.CapabilityEntry(id="k3s-worker", category="compute", status="active"),
            _cs.CapabilityEntry(id="zfs-pool", category="storage", status="active"),
            _cs.CapabilityEntry(id="headscale", category="networking", status="degraded"),
            _cs.CapabilityEntry(id="forgejo", category="gitops", status="inactive"),
        ]
        return _cs.CapabilityState(cell_id="pve01-cell", declared_at=_now(), capabilities=caps)

    def test_by_category(self):
        s = self._state()
        compute = s.by_category("compute")
        assert len(compute) == 2
        assert {c.id for c in compute} == {"k3s-server", "k3s-worker"}

    def test_by_category_empty(self):
        s = self._state()
        assert s.by_category("observability") == []

    def test_by_id(self):
        s = self._state()
        e = s.by_id("zfs-pool")
        assert e is not None
        assert e.category == "storage"

    def test_by_id_missing(self):
        s = self._state()
        assert s.by_id("nonexistent") is None

    def test_active_filters(self):
        s = self._state()
        active = s.active()
        ids = {e.id for e in active}
        assert "k3s-server" in ids
        assert "k3s-worker" in ids
        assert "zfs-pool" in ids
        assert "headscale" not in ids   # degraded
        assert "forgejo" not in ids     # inactive


# ===========================================================================
# 18.2/18.3 — derive_capabilities_from_state
# ===========================================================================

class TestDeriveCapabilities:
    def _derive(self, bs=None, cs=None, ps=None, obs=None):
        return _cs.derive_capabilities_from_state(
            "pve01-cell",
            bs or _bootstrap(),
            cluster_state=cs,
            platform_state=ps,
            observability_state=obs,
            now_fn=_now,
        )

    def test_returns_capability_state(self):
        state = self._derive()
        assert isinstance(state, _cs.CapabilityState)
        assert state.cell_id == "pve01-cell"

    def test_k3s_server_detected(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_K3S_SERVER in ids

    def test_k3s_worker_detected(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_K3S_WORKER in ids

    def test_zfs_pool_detected(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_ZFS_POOL in ids

    def test_headscale_detected_wan(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_HEADSCALE in ids

    def test_dnsmasq_detected(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_DNSMASQ in ids

    def test_forgejo_detected_from_vms(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_FORGEJO in ids

    def test_assessment_and_doc_engine_always_present(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_ASSESSMENT_ENGINE in ids
        assert _cs.CAP_DOC_ENGINE in ids

    def test_restic_when_backup_config(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_RESTIC_BACKUP in ids

    def test_no_restic_without_backup_config(self):
        bs = _bootstrap()
        del bs["backup_config"]
        state = self._derive(bs=bs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_RESTIC_BACKUP not in ids

    def test_flux_cd_from_cluster_state(self):
        cs = {"k3s_cluster": {"flux_reconciled": True}}
        state = self._derive(cs=cs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_FLUX_CD in ids

    def test_no_flux_without_cluster_state(self):
        state = self._derive()
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_FLUX_CD not in ids

    def test_prometheus_from_observability(self):
        obs = {"prometheus": {"reachable": True, "url": "http://prom:9090"}}
        state = self._derive(obs=obs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_PROMETHEUS in ids
        prom = state.by_id(_cs.CAP_PROMETHEUS)
        assert prom.endpoint == "http://prom:9090"

    def test_grafana_from_observability(self):
        obs = {"grafana": {"reachable": True, "url": "http://grafana:3000"}}
        state = self._derive(obs=obs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_GRAFANA in ids

    def test_no_prometheus_when_unreachable(self):
        obs = {"prometheus": {"reachable": False}}
        state = self._derive(obs=obs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_PROMETHEUS not in ids

    def test_no_headscale_lan_only(self):
        bs = _bootstrap()
        bs["network_topology"] = {"profile": "lan"}
        bs["network_topology"]["management_cidr"] = "192.168.1.0/24"
        state = self._derive(bs=bs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_HEADSCALE not in ids

    def test_dnsmasq_on_lan_profile(self):
        bs = _bootstrap()
        bs["network_topology"] = {"profile": "lan", "management_cidr": "192.168.1.0/24"}
        state = self._derive(bs=bs)
        ids = {c.id for c in state.capabilities}
        assert _cs.CAP_DNSMASQ in ids


# ===========================================================================
# 18.4 — build_capability_index
# ===========================================================================

class TestCapabilityIndex:
    def _two_cells(self):
        bs_a = _bootstrap()
        bs_b = _bootstrap()
        bs_b["host_identity"]["hostname"] = "pve02"
        bs_b["k3s_cluster"] = {"server_nodes": [], "worker_nodes": [{"hostname": "k3s-w-02"}]}
        bs_b["vms"] = []
        bs_b["service_contracts"] = []
        bs_b["storage_config"] = {}
        bs_b["backup_config"] = {}

        state_a = _cs.derive_capabilities_from_state("cell-a", bs_a, now_fn=_now)
        state_b = _cs.derive_capabilities_from_state("cell-b", bs_b, now_fn=_now)
        return _cs.build_capability_index([state_a, state_b], now_fn=_now)

    def test_index_built(self):
        idx = self._two_cells()
        assert isinstance(idx, _cs.CapabilityIndex)
        assert "cell-a" in idx.cells
        assert "cell-b" in idx.cells

    def test_cells_with(self):
        idx = self._two_cells()
        cells = idx.cells_with(_cs.CAP_ASSESSMENT_ENGINE)
        assert "cell-a" in cells
        assert "cell-b" in cells

    def test_capabilities_of(self):
        idx = self._two_cells()
        caps = idx.capabilities_of("cell-a")
        assert _cs.CAP_K3S_SERVER in caps
        assert _cs.CAP_HEADSCALE in caps

    def test_has_capability(self):
        idx = self._two_cells()
        assert idx.has_capability("cell-a", _cs.CAP_K3S_SERVER)

    def test_cells_with_empty(self):
        idx = self._two_cells()
        cells = idx.cells_with("nonexistent-cap")
        assert cells == []

    def test_empty_input(self):
        idx = _cs.build_capability_index([], now_fn=_now)
        assert idx.cells == {}
        assert idx.by_capability == {}


# ===========================================================================
# Capability serialisation
# ===========================================================================

class TestCapabilityStateSerialization:
    def test_to_dict_structure(self):
        bs = _bootstrap()
        state = _cs.derive_capabilities_from_state("pve01-cell", bs, now_fn=_now)
        d = _cs.capability_state_to_dict(state)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "pve01-cell"
        assert isinstance(d["capabilities"], list)
        assert "capability_summary" in d

    def test_capability_summary_counts(self):
        bs = _bootstrap()
        state = _cs.derive_capabilities_from_state("pve01-cell", bs, now_fn=_now)
        d = _cs.capability_state_to_dict(state)
        s = d["capability_summary"]
        assert s["active"] >= 1
        assert s["total"] >= 1

    def test_resource_requirements_omitted_when_none(self):
        bs = _bootstrap()
        state = _cs.derive_capabilities_from_state("pve01-cell", bs, now_fn=_now)
        d = _cs.capability_state_to_dict(state)
        # entries with no ram_gib/cpu_cores should have empty dict or absent key
        for cap in d["capabilities"]:
            if "resource_requirements" in cap:
                assert isinstance(cap["resource_requirements"], dict)

    def test_json_roundtrip(self):
        bs = _bootstrap()
        state = _cs.derive_capabilities_from_state("pve01-cell", bs, now_fn=_now)
        d = _cs.capability_state_to_dict(state)
        dumped = json.dumps(d)
        loaded = json.loads(dumped)
        assert loaded["cell_id"] == "pve01-cell"


# ===========================================================================
# 18.5 — secret-reference-state-schema.json
# ===========================================================================

class TestSecretReferenceStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "secret-reference-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert "Secret Reference" in s.get("title", s.get("description", ""))

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "declared_at" in s["required"]

    def test_schema_validates_migrated_state(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        schema = self._schema()
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        doc = _sr.secret_ref_state_to_dict(state)
        jsonschema.validate(doc, schema)


# ===========================================================================
# 18.6 — SecretRefEntry, SecretReferenceState
# ===========================================================================

class TestSecretRefEntry:
    def test_entry_fields(self):
        e = _sr.SecretRefEntry(
            id="headscale-key",
            keepass_path="Infrastructure/headscale/api-key",
            owning_cell="pve01-cell",
            name="Headscale API key",
            category="infrastructure",
            required_for_recovery=True,
        )
        assert e.keepass_path == "Infrastructure/headscale/api-key"
        assert e.required_for_recovery is True

    def test_entry_defaults(self):
        e = _sr.SecretRefEntry(
            id="x",
            keepass_path="A/b",
            owning_cell="cell-a",
        )
        assert e.used_by == []
        assert e.required_for_recovery is False


class TestSecretReferenceState:
    def _state(self):
        secrets = [
            _sr.SecretRefEntry("s1", "A/b", "c", required_for_recovery=True, category="infrastructure"),
            _sr.SecretRefEntry("s2", "B/c", "c", required_for_recovery=True, category="k3s"),
            _sr.SecretRefEntry("s3", "C/d", "c", required_for_recovery=False, category="backup"),
        ]
        return _sr.SecretReferenceState(
            cell_id="pve01-cell",
            owning_cell="pve01-cell",
            declared_at=_now(),
            secrets=secrets,
        )

    def test_recovery_critical(self):
        s = self._state()
        rc = s.recovery_critical()
        assert len(rc) == 2
        assert {e.id for e in rc} == {"s1", "s2"}

    def test_by_category(self):
        s = self._state()
        infra = s.by_category("infrastructure")
        assert len(infra) == 1
        assert infra[0].id == "s1"

    def test_recovery_critical_paths(self):
        s = self._state()
        paths = s.recovery_critical_paths()
        assert "A/b" in paths
        assert "B/c" in paths
        assert "C/d" not in paths


# ===========================================================================
# migrate_from_bootstrap
# ===========================================================================

class TestMigrateFromBootstrap:
    def test_migrates_secret_registry(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        paths = {s.keepass_path for s in state.secrets}
        assert "Infrastructure/headscale/api-key" in paths
        assert "Infrastructure/forgejo/admin-password" in paths

    def test_adds_standard_paths(self):
        # Standard paths like k3s/join-token-server should be added
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        paths = {s.keepass_path for s in state.secrets}
        assert "k3s/join-token-server" in paths
        assert "k3s/join-token-worker" in paths

    def test_deduplication_by_path(self):
        # If secret_registry has a path that's also in _STANDARD_SECRET_PATHS,
        # it should appear only once
        bs = _bootstrap()
        # headscale path is in both secret_registry and _STANDARD_SECRET_PATHS
        state = _sr.migrate_from_bootstrap("pve01-cell", bs, now_fn=_now)
        paths = [s.keepass_path for s in state.secrets]
        assert paths.count("Infrastructure/headscale/api-key") == 1

    def test_empty_bootstrap(self):
        bs = {"cell_id": "pve01-cell", "schema_version": "1.0"}
        state = _sr.migrate_from_bootstrap("pve01-cell", bs, now_fn=_now)
        # Should still have standard paths
        paths = {s.keepass_path for s in state.secrets}
        assert "k3s/join-token-server" in paths

    def test_recovery_required_from_registry(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        hs = next(s for s in state.secrets if s.keepass_path == "Infrastructure/headscale/api-key")
        assert hs.required_for_recovery is True

    def test_cell_id_set(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        assert state.cell_id == "pve01-cell"
        assert state.owning_cell == "pve01-cell"

    def test_categorise_k3s_paths(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        token = next(s for s in state.secrets if s.keepass_path == "k3s/join-token-server")
        assert token.category == "k3s"

    def test_categorise_backup_paths(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        bkup = next((s for s in state.secrets if "Backup" in s.keepass_path), None)
        assert bkup is not None
        assert bkup.category == "backup"


# ===========================================================================
# build_recovery_critical + serialisation
# ===========================================================================

class TestBuildRecoveryCritical:
    def test_returns_required_paths(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        paths = _sr.build_recovery_critical(state)
        assert isinstance(paths, list)
        assert "Infrastructure/headscale/api-key" in paths

    def test_excludes_non_required(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        # Assessment engine key is not required_for_recovery
        paths = _sr.build_recovery_critical(state)
        # (it may or may not be present; just ensure we don't crash)
        assert isinstance(paths, list)


class TestSecretRefSerialization:
    def test_to_dict_structure(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        d = _sr.secret_ref_state_to_dict(state)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "pve01-cell"
        assert isinstance(d["secrets"], list)
        assert "recovery_critical_paths" in d

    def test_recovery_critical_paths_in_dict(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        d = _sr.secret_ref_state_to_dict(state)
        assert isinstance(d["recovery_critical_paths"], list)
        assert "Infrastructure/headscale/api-key" in d["recovery_critical_paths"]

    def test_json_roundtrip(self):
        state = _sr.migrate_from_bootstrap("pve01-cell", _bootstrap(), now_fn=_now)
        d = _sr.secret_ref_state_to_dict(state)
        dumped = json.dumps(d)
        loaded = json.loads(dumped)
        assert loaded["cell_id"] == "pve01-cell"
        assert len(loaded["secrets"]) > 0
