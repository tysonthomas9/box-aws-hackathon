import groups from "virtual:demo-prompts";

export function starterGroup(versionId) {
  const halvard = /halvard|poc/i.test(versionId ?? "");
  return {
    label: halvard ? "Halvard (Phase 1)" : "Medical (Rubber Ducks)",
    prompts: halvard ? groups.halvard : groups.medical,
  };
}
