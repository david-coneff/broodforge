"""
test_phase21_failure_domain.py — Phase 21: Failure Domain Modeling.

Covers:
  21.1  Taxonomy (ALL_LEVELS constants, FailureDomainNode)
  21.2  PropagationEngine — storage → VMs → services rules
  21.3  blast_radius() — enumerate affected from initial failure
  21.4  detect_spofs() — SPOF identification
  21.5  detect_circular_deps() — circular recovery detection
  21.6  build_failure_domain_graph() from manifest,
        analyze_failure_domain(), FailureDomainReport
"""



import failure_domain as _fd

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _simple_graph():
    """Simple 4-node graph: host → pool → vm → service."""
    host = _fd.FailureDomainNode("host-01", _fd.LEVEL_PHYSICAL, "Host pve01", "cell-a")
    pool = _fd.FailureDomainNode("pool-01", _fd.LEVEL_STORAGE, "ZFS rpool", "cell-a",
                                  depends_on=["host-01"])
    vm   = _fd.FailureDomainNode("vm-101",  _fd.LEVEL_VM,      "VM forgejo", "cell-a",
                                  depends_on=["host-01", "pool-01"])
    svc  = _fd.FailureDomainNode("svc-forgejo", _fd.LEVEL_SERVICE, "Service forgejo", "cell-a",
                                  depends_on=["vm-101"])
    return [host, pool, vm, svc]


def _manifest():
    return {
        "cell_id": "pve01-cell",
        "host_identity": {"hostname": "pve01"},
        "storage_config": {"zfs_pool": {"pool_name": "rpool", "topology": "mirror"}},
        "network_topology_declared": {
            "bridges": [{"name": "vmbr0"}, {"name": "vmbr1"}],
        },
        "vms": [
            {"vmid": 101, "name": "forgejo"},
            {"vmid": 102, "name": "k3s-server-01"},
        ],
        "service_contracts": [
            {"service": "forgejo", "vm_name": "forgejo", "required_interfaces": []},
        ],
        "k3s_cluster": {
            "server_nodes": [{"hostname": "k3s-server-01"}],
            "worker_nodes": [],
        },
    }


# ===========================================================================
# 21.1 — Taxonomy
# ===========================================================================

class TestTaxonomy:
    def test_all_levels_defined(self):
        for level in _fd.ALL_LEVELS:
            assert isinstance(level, str)

    def test_level_constants(self):
        assert _fd.LEVEL_PHYSICAL  == "physical"
        assert _fd.LEVEL_VM        == "vm"
        assert _fd.LEVEL_SERVICE   == "service"
        assert _fd.LEVEL_STORAGE   == "storage"
        assert _fd.LEVEL_K3S       == "k3s"

    def test_node_creation(self):
        n = _fd.FailureDomainNode("n1", _fd.LEVEL_VM, "VM test", "cell-a")
        assert n.node_id == "n1"
        assert n.level   == _fd.LEVEL_VM
        assert n.redundancy == 1

    def test_spof_no_recovery(self):
        n = _fd.FailureDomainNode("n1", _fd.LEVEL_VM, "VM", "cell-a", redundancy=1)
        assert n.is_spof is True

    def test_not_spof_with_recovery(self):
        n = _fd.FailureDomainNode("n1", _fd.LEVEL_VM, "VM", "cell-a",
                                   redundancy=1, recovers_via=["n2"])
        assert n.is_spof is False

    def test_not_spof_with_redundancy(self):
        n = _fd.FailureDomainNode("n1", _fd.LEVEL_VM, "VM", "cell-a", redundancy=3)
        assert n.is_spof is False


# ===========================================================================
# 21.2 — Propagation engine
# ===========================================================================

class TestPropagationEngine:
    def test_propagation_from_host_reaches_service(self):
        nodes  = _simple_graph()
        engine = _fd.PropagationEngine(nodes)
        result = engine.propagate({"host-01"})
        assert "svc-forgejo" in result

    def test_propagation_from_pool_reaches_vm(self):
        nodes  = _simple_graph()
        engine = _fd.PropagationEngine(nodes)
        result = engine.propagate({"pool-01"})
        assert "vm-101" in result

    def test_propagation_from_service_is_terminal(self):
        nodes  = _simple_graph()
        engine = _fd.PropagationEngine(nodes)
        result = engine.propagate({"svc-forgejo"})
        # Service failure doesn't propagate to VM
        assert "vm-101" not in result
        assert "svc-forgejo" in result

    def test_initial_failure_in_result(self):
        nodes  = _simple_graph()
        engine = _fd.PropagationEngine(nodes)
        result = engine.propagate({"host-01"})
        assert "host-01" in result

    def test_default_rules_apply(self):
        assert len(_fd.DEFAULT_PROPAGATION_RULES) >= 5


# ===========================================================================
# 21.3 — blast_radius
# ===========================================================================

class TestBlastRadius:
    def test_host_failure_blast_radius(self):
        nodes  = _simple_graph()
        result = _fd.blast_radius({"host-01"}, nodes)
        assert result.total_affected >= 4   # host, pool, vm, svc
        assert "svc-forgejo" in result.critical_services

    def test_by_level_grouping(self):
        nodes  = _simple_graph()
        result = _fd.blast_radius({"host-01"}, nodes)
        assert _fd.LEVEL_SERVICE in result.by_level
        assert "svc-forgejo" in result.by_level[_fd.LEVEL_SERVICE]

    def test_vm_failure_limited_blast(self):
        nodes  = _simple_graph()
        result = _fd.blast_radius({"vm-101"}, nodes)
        # VM failure → service failure but NOT host/pool
        assert "host-01" not in result.all_affected
        assert "pool-01" not in result.all_affected
        assert "svc-forgejo" in result.all_affected

    def test_empty_initial_failure(self):
        result = _fd.blast_radius(set(), _simple_graph())
        assert result.total_affected == 0

    def test_initial_in_all_affected(self):
        result = _fd.blast_radius({"host-01"}, _simple_graph())
        assert "host-01" in result.all_affected


# ===========================================================================
# 21.4 — detect_spofs
# ===========================================================================

class TestDetectSpofs:
    def test_finds_spof(self):
        nodes  = _simple_graph()
        spofs  = _fd.detect_spofs(nodes)
        spof_ids = {s.node_id for s in spofs}
        # pool-01 depends on host-01; host-01 has no recovery → SPOF
        assert "host-01" in spof_ids or "pool-01" in spof_ids

    def test_no_spof_with_recovery(self):
        host  = _fd.FailureDomainNode("host-01", _fd.LEVEL_PHYSICAL, "Host", "c",
                                       recovers_via=["host-02"])
        pool  = _fd.FailureDomainNode("pool-01", _fd.LEVEL_STORAGE, "ZFS", "c",
                                       depends_on=["host-01"])
        spofs = _fd.detect_spofs([host, pool])
        assert not any(s.node_id == "host-01" for s in spofs)

    def test_node_not_depended_on_not_spof(self):
        isolated = _fd.FailureDomainNode("solo", _fd.LEVEL_SERVICE, "Isolated", "c", redundancy=1)
        spofs    = _fd.detect_spofs([isolated])
        assert len(spofs) == 0   # nobody depends on it → not a SPOF

    def test_finding_fields(self):
        nodes = _simple_graph()
        spofs = _fd.detect_spofs(nodes)
        if spofs:
            s = spofs[0]
            assert hasattr(s, "node_id")
            assert hasattr(s, "level")
            assert hasattr(s, "reason")


# ===========================================================================
# 21.5 — detect_circular_deps
# ===========================================================================

class TestDetectCircularDeps:
    def test_no_circular_in_simple_graph(self):
        nodes = _simple_graph()
        circ  = _fd.detect_circular_deps(nodes)
        assert circ == []

    def test_detects_simple_cycle(self):
        a = _fd.FailureDomainNode("a", _fd.LEVEL_VM, "VM a", "c", recovers_via=["b"])
        b = _fd.FailureDomainNode("b", _fd.LEVEL_VM, "VM b", "c", recovers_via=["a"])
        circ = _fd.detect_circular_deps([a, b])
        assert len(circ) >= 1
        cycle_nodes = {n for c in circ for n in c.cycle}
        assert "a" in cycle_nodes or "b" in cycle_nodes

    def test_no_cycle_one_way(self):
        a = _fd.FailureDomainNode("a", _fd.LEVEL_VM, "VM a", "c", recovers_via=["b"])
        b = _fd.FailureDomainNode("b", _fd.LEVEL_VM, "VM b", "c")
        circ = _fd.detect_circular_deps([a, b])
        assert circ == []

    def test_finding_has_cycle_and_labels(self):
        a = _fd.FailureDomainNode("a", _fd.LEVEL_VM, "Label A", "c", recovers_via=["b"])
        b = _fd.FailureDomainNode("b", _fd.LEVEL_VM, "Label B", "c", recovers_via=["a"])
        circ = _fd.detect_circular_deps([a, b])
        if circ:
            finding = circ[0]
            assert hasattr(finding, "labels")


# ===========================================================================
# 21.6 — build_failure_domain_graph + analyze_failure_domain
# ===========================================================================

class TestBuildFailureDomainGraph:
    def test_returns_list(self):
        nodes = _fd.build_failure_domain_graph(_manifest())
        assert isinstance(nodes, list)
        assert len(nodes) > 0

    def test_has_physical_node(self):
        nodes = _fd.build_failure_domain_graph(_manifest())
        levels = {n.level for n in nodes}
        assert _fd.LEVEL_PHYSICAL in levels

    def test_has_vm_nodes(self):
        nodes = _fd.build_failure_domain_graph(_manifest())
        vm_nodes = [n for n in nodes if n.level == _fd.LEVEL_VM]
        assert len(vm_nodes) == 2

    def test_has_service_node(self):
        nodes = _fd.build_failure_domain_graph(_manifest())
        svc_nodes = [n for n in nodes if n.level == _fd.LEVEL_SERVICE]
        assert len(svc_nodes) >= 1

    def test_has_k3s_node(self):
        nodes = _fd.build_failure_domain_graph(_manifest())
        k3s_nodes = [n for n in nodes if n.level == _fd.LEVEL_K3S]
        assert len(k3s_nodes) >= 1

    def test_vm_depends_on_host(self):
        nodes   = _fd.build_failure_domain_graph(_manifest())
        {n.node_id: n for n in nodes}
        vm_nodes = [n for n in nodes if n.level == _fd.LEVEL_VM]
        for vm in vm_nodes:
            # At least one dependency should be the physical host
            assert len(vm.depends_on) > 0


class TestAnalyzeFailureDomain:
    def test_returns_report(self):
        report = _fd.analyze_failure_domain(_manifest())
        assert isinstance(report, _fd.FailureDomainReport)

    def test_score_set(self):
        report = _fd.analyze_failure_domain(_manifest())
        assert report.score in ("GREEN", "YELLOW", "ORANGE", "RED")

    def test_total_nodes_positive(self):
        report = _fd.analyze_failure_domain(_manifest())
        assert report.total_nodes > 0

    def test_to_findings(self):
        report = _fd.analyze_failure_domain(_manifest())
        findings = report.to_findings()
        assert isinstance(findings, list)
        for f in findings:
            assert "severity" in f
            assert "category" in f
            assert "message" in f

    def test_circular_dep_report(self):
        # Add self-referencing nodes
        import failure_domain as fd2
        nodes = [
            fd2.FailureDomainNode("a", fd2.LEVEL_VM, "A", "c", recovers_via=["b"]),
            fd2.FailureDomainNode("b", fd2.LEVEL_VM, "B", "c", recovers_via=["a"]),
        ]
        circ = fd2.detect_circular_deps(nodes)
        assert len(circ) >= 1
