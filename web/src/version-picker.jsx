import React, { useEffect, useState } from "react";
import { Button } from "@openuidev/react-ui/Button";
import "./versions.css";

const KEY = "kloop-selected-version";
export function useVersionPicker(api) {
  const [catalog, setCatalog] = useState(null);
  const [choice, setChoice] = useState(() => sessionStorage.getItem(KEY) ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let mounted = true;
    const load = () =>
      api("versions")
        .then((data) => {
          if (mounted) {
            setCatalog(data);
            setError("");
          }
        })
        .catch((e) => {
          if (mounted) setError(e.message);
        });
    load();
    const timer = setInterval(() => {
      if (!document.getElementById("ask")?.hidden) load();
    }, 15000);
    window.addEventListener("kloop:ask-open", load);
    return () => {
      mounted = false;
      clearInterval(timer);
      window.removeEventListener("kloop:ask-open", load);
    };
  }, [api]);
  const id = choice || catalog?.default_version_id;
  const selected = catalog?.versions.find((v) => v.id === id);
  const choose = (value) => {
    setChoice(value);
    if (value) sessionStorage.setItem(KEY, value);
    else sessionStorage.removeItem(KEY);
  };
  async function action(kind, id = selected?.id) {
    if (!id || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`versions/${encodeURIComponent(id)}/${kind}`, {});
      setCatalog(await api("versions"));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const unavailable = Boolean(
    choice && (!selected || selected.state !== "loaded"),
  );
  return {
    catalog,
    choice,
    selected,
    choose,
    action,
    busy,
    error,
    unavailable,
  };
}
export function VersionPicker({ picker }) {
  const [unloadId, setUnloadId] = useState("");
  const { catalog, choice, selected, choose, action, busy, error } = picker;
  return (
    <div className="version-picker">
      <label>
        Trained version
        <select
          aria-label="Trained version"
          value={choice}
          onChange={(e) => choose(e.target.value)}
          disabled={busy || !catalog}
        >
          <option value="">Automatic · promoted or temporary</option>
          {choice && !catalog?.versions.some((v) => v.id === choice) && (
            <option value={choice}>{choice} · unavailable</option>
          )}
          {catalog?.versions.map((v) => (
            <option key={v.id} value={v.id}>
              {v.id} · {v.status} · {v.state.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <p className="subtle">
        This browser session only. Promotion is unchanged.
      </p>
      {selected && (
        <>
          <p className="version-summary">
            {selected.status} · {selected.state.replaceAll("_", " ")}
            {selected.created_at && (
              <> · {new Date(selected.created_at * 1000).toLocaleString()}</>
            )}
          </p>
          <details>
            <summary>Import and dev score</summary>
            <p className="binding">
              {selected.import_arn ?? "No loaded import"}
            </p>
            <pre>
              {selected.dev_score
                ? JSON.stringify(selected.dev_score, null, 2)
                : "Dev score not recorded"}
            </pre>
          </details>
          <div className="actions version-actions">
            <Button
              type="button"
              variant="secondary"
              size="small"
              disabled={busy || !selected.can_load || catalog.load_active}
              onClick={() => action("load")}
            >
              Load version
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="small"
              disabled={busy || !selected.can_unload || catalog.load_active}
              onClick={() => action("unload")}
            >
              Unload version
            </Button>
          </div>
          {selected.state !== "loaded" && (
            <p role="status">
              {selected.state === "loading"
                ? "Import is loading. This page refreshes automatically."
                : "Load this version before asking it a question."}
            </p>
          )}
          <p className="subtle">
            Import: about 10–30 minutes. First answer: up to 14 minutes when
            cold.
          </p>
          {catalog.slots_used >= catalog.slot_limit &&
            selected.state !== "loaded" && (
              <div className="slot-choice">
                <label>
                  Version to unload
                  <select
                    aria-label="Version to unload"
                    value={unloadId}
                    onChange={(e) => setUnloadId(e.target.value)}
                    disabled={busy}
                  >
                    <option value="">Choose a version to free a slot</option>
                    {catalog.versions
                      .filter((v) => v.can_unload)
                      .map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.id}
                        </option>
                      ))}
                  </select>
                </label>
                <Button
                  type="button"
                  variant="secondary"
                  size="small"
                  disabled={
                    busy ||
                    !catalog.versions.some(
                      (v) => v.id === unloadId && v.can_unload,
                    )
                  }
                  onClick={() => action("unload", unloadId)}
                >
                  Unload selected version
                </Button>
                <p className="subtle">
                  All import slots are used. Unload an available version, wait
                  for the slot to clear, then load this version.
                </p>
              </div>
            )}
        </>
      )}
      {catalog && (
        <p className="subtle">
          Import slots: {catalog.slots_used} / {catalog.slot_limit}
        </p>
      )}
      {catalog?.load_active && (
        <p role="status">
          Training or model loading is active. Wait before changing loaded
          versions.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
