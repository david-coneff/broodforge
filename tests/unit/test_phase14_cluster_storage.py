"""
test_phase14_cluster_storage.py — Tests for Phase 14: Cluster and Storage State.

Covers:
  14.1  data-model/cluster-state-schema.json
  14.2  cluster_state_collector.py — parsers, dataclasses, compute_cluster_health
  14.3  data-model/storage-state-schema.json
  14.4  storage_state_collector.py — parsers, dataclasses, compute_storage_health
  14.5/14.6  readiness.py — cluster + storage state scorers
"""

import json
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))
sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))

import cluster_state_collector  as _cs
import storage_state_collector   as _ss


# ===========================================================================
# 14.1 — cluster-state-schema.json
# ===========================================================================

class TestClusterStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "cluster-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Cluster State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "collected_at" in s["required"]

    def test_proxmox_node_has_online(self):
        s = self._schema()
        node = s["definitions"]["proxmox_node"]["properties"]
        assert "online" in node

    def test_k3s_node_has_status(self):
        s = self._schema()
        node = s["definitions"]["k3s_node"]["properties"]
        assert "status" in node

    def test_valid_minimal(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")
        s = self._schema()
        jsonschema.validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }, s)


# ===========================================================================
# 14.3 — storage-state-schema.json
# ===========================================================================

class TestStorageStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "storage-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Storage State"

    def test_zfs_pool_has_state(self):
        s = self._schema()
        pool = s["definitions"]["zfs_pool"]["properties"]
        assert "state" in pool

    def test_pbs_job_has_last_status(self):
        s = self._schema()
        job = s["definitions"]["pbs_job"]["properties"]
        assert "last_status" in job

    def test_valid_minimal(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")
        s = self._schema()
        jsonschema.validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }, s)


# ===========================================================================
# 14.2 — cluster_state_collector parsers
# ===========================================================================

_PVECM_STATUS = """\
Cluster information
-------------------
Name:             broodforge-cluster
Config Version:   1
Transport:        knet
Secure auth:      on

Quorum information
------------------
Date:             Mon Jun  1 12:00:00 2026
Quorum provider:  corosync_votequorum
Nodes:            2
Node state:       Quorum OK

Membership information
----------------------
    Nodeid      Votes Name
         1          1 pve01 (local)
         2          1 pve02
"""

_PVECM_NODES = """\
Membership information
----------------------
    Nodeid      Votes Name
         1          1 pve01
         2          1 pve02
"""

_KUBECTL_NODES_JSON = json.dumps({
    "items": [
        {
            "metadata": {
                "name": "pve01-k3s",
                "labels": {"node-role.kubernetes.io/control-plane": "true"},
            },
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "nodeInfo": {"kubeletVersion": "v1.28.5+k3s1", "osImage": "Ubuntu 22.04"},
                "addresses": [{"type": "InternalIP", "address": "192.168.1.11"}],
            },
            "spec": {"taints": []},
        },
        {
            "metadata": {
                "name": "pve02-worker",
                "labels": {},
            },
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "nodeInfo": {"kubeletVersion": "v1.28.5+k3s1"},
                "addresses": [{"type": "InternalIP", "address": "192.168.1.12"}],
            },
            "spec": {},
        },
    ]
})


class TestParsePvecmStatus:
    def test_name_parsed(self):
        result = _cs._parse_pvecm_status(_PVECM_STATUS)
        assert result.get("name") == "broodforge-cluster"

    def test_quorum_ok_parsed(self):
        result = _cs._parse_pvecm_status(_PVECM_STATUS)
        assert result.get("quorum_ok") is True

    def test_quorum_not_ok(self):
        out = "Quorum not OK\n"
        result = _cs._parse_pvecm_status(out)
        assert result.get("quorum_ok") is False

    def test_empty_returns_empty(self):
        result = _cs._parse_pvecm_status("")
        assert result == {}


class TestParsePvecmNodes:
    def test_returns_nodes(self):
        nodes = _cs._parse_pvecm_nodes(_PVECM_NODES)
        assert len(nodes) == 2

    def test_node_names(self):
        nodes = _cs._parse_pvecm_nodes(_PVECM_NODES)
        names = [n.name for n in nodes]
        assert "pve01" in names
        assert "pve02" in names


class TestParseKubectlNodesJson:
    def test_returns_k3s_nodes(self):
        nodes = _cs._parse_kubectl_nodes_json(_KUBECTL_NODES_JSON)
        assert len(nodes) == 2

    def test_control_plane_role(self):
        nodes = _cs._parse_kubectl_nodes_json(_KUBECTL_NODES_JSON)
        cp = next(n for n in nodes if n.name == "pve01-k3s")
        assert "control-plane" in cp.roles

    def test_ready_status(self):
        nodes = _cs._parse_kubectl_nodes_json(_KUBECTL_NODES_JSON)
        assert all(n.status == "Ready" for n in nodes)

    def test_internal_ip(self):
        nodes = _cs._parse_kubectl_nodes_json(_KUBECTL_NODES_JSON)
        cp = next(n for n in nodes if n.name == "pve01-k3s")
        assert cp.internal_ip == "192.168.1.11"

    def test_invalid_json_returns_empty(self):
        nodes = _cs._parse_kubectl_nodes_json("not json")
        assert nodes == []


class TestClusterStateDocument:
    def _doc(self, **kw):
        return _cs.ClusterStateDocument(
            cell_id="test-cell",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_defaults(self):
        doc = self._doc()
        assert doc.proxmox_nodes == []
        assert doc.k3s_nodes == []

    def test_cluster_state_to_dict(self):
        doc = self._doc()
        d = _cs.cluster_state_to_dict(doc)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "test-cell"

    def test_compute_health_no_data(self):
        doc = self._doc()
        health = _cs.compute_cluster_health(doc)
        assert health["overall_status"] == "UNKNOWN"

    def test_compute_health_all_ready(self):
        nodes = [
            _cs.K3sNode(name="n1", status="Ready"),
            _cs.K3sNode(name="n2", status="Ready"),
        ]
        doc = self._doc(k3s_nodes=nodes, quorum_ok=True)
        health = _cs.compute_cluster_health(doc)
        assert health["overall_status"] == "HEALTHY"
        assert health["all_k3s_nodes_ready"] is True

    def test_compute_health_not_ready_node(self):
        nodes = [
            _cs.K3sNode(name="n1", status="Ready"),
            _cs.K3sNode(name="n2", status="NotReady"),
        ]
        doc = self._doc(k3s_nodes=nodes, quorum_ok=True)
        health = _cs.compute_cluster_health(doc)
        assert health["all_k3s_nodes_ready"] is False
        assert "n2" in str(health.get("issues", []))

    def test_compute_health_quorum_failed(self):
        doc = self._doc(quorum_ok=False)
        health = _cs.compute_cluster_health(doc)
        assert health["overall_status"] == "CRITICAL"


# ===========================================================================
# 14.4 — storage_state_collector parsers
# ===========================================================================

_ZPOOL_STATUS = """\
  pool: rpool
 state: ONLINE
status: Some supported features are not enabled on the pool.
  scan: scrub repaired 0B in 00:01:02 with 0 errors on Sun Jan  1 00:00:00 2026
  pool: rpool
  NAME    STATE     READ WRITE CKSUM
  rpool   ONLINE       0     0     0
    mirror-0  ONLINE     0     0     0
      sda   ONLINE       0     0     0
      sdb   ONLINE       0     0     0
"""

_PVESM_STATUS = """\
Name             Type     Status           Total            Used       Available        %
local            dir      active       73317888       12567552       57190144           17%
local-zfs        zfspool  active      449091224        5128192      443963032            1%
"""


class TestParseZpoolStatus:
    def test_returns_pools(self):
        pools = _ss._parse_zpool_status(_ZPOOL_STATUS)
        assert len(pools) >= 1

    def test_pool_name(self):
        pools = _ss._parse_zpool_status(_ZPOOL_STATUS)
        assert pools[0].name == "rpool"

    def test_pool_state(self):
        pools = _ss._parse_zpool_status(_ZPOOL_STATUS)
        assert pools[0].state == "ONLINE"


class TestParsePvesmStatus:
    def test_returns_datastores(self):
        stores = _ss._parse_pvesm_status(_PVESM_STATUS)
        assert len(stores) >= 1

    def test_store_id(self):
        stores = _ss._parse_pvesm_status(_PVESM_STATUS)
        ids = [s.id for s in stores]
        assert "local" in ids

    def test_store_enabled(self):
        stores = _ss._parse_pvesm_status(_PVESM_STATUS)
        local = next(s for s in stores if s.id == "local")
        assert local.enabled is True


class TestBytesToGb:
    def test_bytes(self):
        result = _ss._bytes_to_gb("107374182400")  # 100 GiB
        assert result is not None
        assert 99 < result < 101

    def test_g_suffix(self):
        result = _ss._bytes_to_gb("500G")
        assert result == 500.0

    def test_t_suffix(self):
        result = _ss._bytes_to_gb("2T")
        assert result == 2048.0

    def test_none_returns_none(self):
        result = _ss._bytes_to_gb(None)
        assert result is None


class TestStorageStateDocument:
    def _doc(self, **kw):
        return _ss.StorageStateDocument(
            cell_id="test-cell",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_defaults(self):
        doc = self._doc()
        assert doc.zfs_pools == []

    def test_storage_state_to_dict(self):
        doc = self._doc()
        d = _ss.storage_state_to_dict(doc)
        assert d["schema_version"] == "1.0"

    def test_compute_health_no_pools(self):
        doc = self._doc()
        health = _ss.compute_storage_health(doc)
        assert health["pool_health_summary"] == "UNKNOWN"
        assert health["overall_status"] == "UNKNOWN"

    def test_compute_health_all_online(self):
        doc = self._doc(zfs_pools=[
            _ss.ZfsPool(name="rpool", state="ONLINE", capacity_pct=50),
        ])
        health = _ss.compute_storage_health(doc)
        assert health["pool_health_summary"] == "ALL_ONLINE"
        assert health["overall_status"] == "HEALTHY"

    def test_compute_health_degraded_pool(self):
        doc = self._doc(zfs_pools=[
            _ss.ZfsPool(name="rpool", state="DEGRADED"),
        ])
        health = _ss.compute_storage_health(doc)
        assert health["pool_health_summary"] == "DEGRADED"
        assert health["overall_status"] == "DEGRADED"

    def test_compute_health_faulted_pool(self):
        doc = self._doc(zfs_pools=[
            _ss.ZfsPool(name="rpool", state="FAULTED"),
        ])
        health = _ss.compute_storage_health(doc)
        assert health["pool_health_summary"] == "FAULTED"
        assert health["overall_status"] == "CRITICAL"

    def test_high_capacity_warning(self):
        doc = self._doc(zfs_pools=[
            _ss.ZfsPool(name="rpool", state="ONLINE", capacity_pct=85),
        ])
        health = _ss.compute_storage_health(doc)
        assert "rpool" in health["high_capacity_pools"]
        assert health["overall_status"] == "DEGRADED"

    def test_pbs_failure_detected(self):
        doc = self._doc(pbs_jobs=[
            _ss.PbsJob(id="job-100", last_status="error"),
        ])
        health = _ss.compute_storage_health(doc)
        assert "job-100" in health["pbs_job_failures"]


# ===========================================================================
# 14.5/14.6 — readiness scoring
# ===========================================================================

from readiness import _score_cluster_state_completeness, _score_storage_state_completeness


class TestScoreClusterStateCompleteness:
    def test_no_cluster_state_yellow(self):
        gaps = _score_cluster_state_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"

    def test_no_cluster_state_gap_type(self):
        gaps = _score_cluster_state_completeness({})
        assert gaps[0].gap_type == "MISSING_CLUSTER_STATE"

    def test_healthy_cluster_no_gaps(self):
        manifest = {
            "cluster_state": {
                "cluster_health": {"overall_status": "HEALTHY"}
            }
        }
        gaps = _score_cluster_state_completeness(manifest)
        assert not gaps

    def test_critical_cluster_orange(self):
        manifest = {
            "cluster_state": {
                "cluster_health": {
                    "overall_status": "CRITICAL",
                    "issues": ["quorum lost"],
                }
            }
        }
        gaps = _score_cluster_state_completeness(manifest)
        assert any(g.severity == "ORANGE" and "CRITICAL" in g.gap_type for g in gaps)

    def test_degraded_cluster_yellow(self):
        manifest = {
            "cluster_state": {
                "cluster_health": {"overall_status": "DEGRADED"}
            }
        }
        gaps = _score_cluster_state_completeness(manifest)
        assert any(g.severity == "YELLOW" for g in gaps)


class TestScoreStorageStateCompleteness:
    def test_no_storage_state_yellow(self):
        gaps = _score_storage_state_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"

    def test_no_storage_state_gap_type(self):
        gaps = _score_storage_state_completeness({})
        assert gaps[0].gap_type == "MISSING_STORAGE_STATE"

    def test_healthy_storage_no_gaps(self):
        manifest = {
            "storage_state": {
                "storage_health": {
                    "overall_status": "HEALTHY",
                    "pool_health_summary": "ALL_ONLINE",
                    "high_capacity_pools": [],
                    "pbs_job_failures": [],
                }
            }
        }
        gaps = _score_storage_state_completeness(manifest)
        assert not gaps

    def test_critical_storage_orange(self):
        manifest = {
            "storage_state": {
                "storage_health": {
                    "overall_status": "CRITICAL",
                    "pool_health_summary": "FAULTED",
                    "high_capacity_pools": [],
                    "pbs_job_failures": [],
                    "issues": ["ZFS pool faulted"],
                }
            }
        }
        gaps = _score_storage_state_completeness(manifest)
        assert any(g.severity == "ORANGE" for g in gaps)

    def test_pbs_failure_orange(self):
        manifest = {
            "storage_state": {
                "storage_health": {
                    "overall_status": "DEGRADED",
                    "pool_health_summary": "ALL_ONLINE",
                    "high_capacity_pools": [],
                    "pbs_job_failures": ["job-100"],
                }
            }
        }
        gaps = _score_storage_state_completeness(manifest)
        assert any(g.gap_type == "PBS_BACKUP_FAILURES" for g in gaps)

    def test_degraded_storage_yellow(self):
        manifest = {
            "storage_state": {
                "storage_health": {
                    "overall_status": "DEGRADED",
                    "pool_health_summary": "DEGRADED",
                    "high_capacity_pools": [],
                    "pbs_job_failures": [],
                    "issues": ["pool degraded"],
                }
            }
        }
        gaps = _score_storage_state_completeness(manifest)
        assert any(g.severity == "YELLOW" for g in gaps)
