// TEST-ONLY synthetic definitions and records. Not producer or device evidence.
export function definitionFixture() {
  return {
    name: " Policy 🧪 ",
    objective: " Observe\npolicy\t ",
    target_id: "dut-test",
    sink_id: "sink-test",
    dut_version: " firmware ",
    policy_version: " policy ",
    profile_id: "tcpreplay-policy" as const,
    protocol: "TCP" as const,
    ip_version: 4 as const,
    expected_action: "ALLOW" as const,
    delivery_expectation: "ALLOW" as const,
    detection_required: false,
    pcap_asset: null,
    traffic_budget: {
      max_pps: 100,
      max_bps: 1000,
      max_packets: 1000,
      max_bytes: 10000,
      max_connections: 10,
      duration_seconds: 10,
    },
    success_criteria: {
      minimum_delivery_pct: 95,
      maximum_delivery_pct: 100,
      detection_deadline_ms: null,
    },
    stop_conditions: {
      max_legitimate_loss_pct: 1,
      max_service_latency_ms: 100,
      max_cpu_pct: null,
      max_memory_pct: null,
      max_sessions: null,
      management_loss: true as const,
    },
    evidence_requirements: ["ingress_pcap", "egress_pcap", "service_probe"],
  };
}
