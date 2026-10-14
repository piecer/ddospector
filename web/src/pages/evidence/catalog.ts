// Generated metadata from unchanged P2-00 CLI output; no outcome oracle.
export const sampleCatalog = [
  {
    sample_id: "complete",
    coverage: "COMPLETE_SYNTHETIC",
    ingress: {
      filename: "complete-ingress.pcap",
      size_bytes: 1064,
      sha256:
        "064da0d37bd6b82c18182fdfd72ebe2b328b3e243c62f3da152a960e75c05a63",
      packet_count: 10,
    },
    egress: {
      filename: "complete-egress.pcap",
      size_bytes: 1064,
      sha256:
        "e5d012a2779605d06d12312566738cfba90a20ca5b9c6008c7cc622baa7e2eea",
      packet_count: 10,
    },
  },
  {
    sample_id: "violation",
    coverage: "COMPLETE_SYNTHETIC",
    ingress: {
      filename: "violation-ingress.pcap",
      size_bytes: 1074,
      sha256:
        "db8ae337ff672bd4fd0b311ad4ecccf5856ddb1f456c99bffbc3771a649bf33c",
      packet_count: 10,
    },
    egress: {
      filename: "violation-egress.pcap",
      size_bytes: 969,
      sha256:
        "b86f710f4613123adc409e1bcc7f5db51506014b9591603c26eaf41e82740c7b",
      packet_count: 9,
    },
  },
  {
    sample_id: "unknown",
    coverage: "UNKNOWN",
    ingress: {
      filename: "unknown-ingress.pcap",
      size_bytes: 1054,
      sha256:
        "4327ed35bc862f1de5b9dcb676e22a4a4348e6a4a6c908a94dbf2f1ec09aa732",
      packet_count: 10,
    },
    egress: {
      filename: "unknown-egress.pcap",
      size_bytes: 951,
      sha256:
        "35b0a9e13f70ab8d66202abd6cbfe91276d45437587c85d10f43a8b06958a1f7",
      packet_count: 9,
    },
  },
] as const;
export const manifestSHA =
  "517c2fbe09f6afa50587f7db481f54bd8b9bc1576f70e393a3aba69ef54bc228";
