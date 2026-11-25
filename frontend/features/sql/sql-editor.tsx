"use client";
import { useMemo } from "react";
import CodeMirror, { EditorView, keymap, Prec } from "@uiw/react-codemirror";
import { sql, PostgreSQL } from "@codemirror/lang-sql";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

const highlight = HighlightStyle.define([
  { tag: t.keyword, color: "var(--accent)", fontWeight: "600" },
  { tag: [t.string, t.special(t.string)], color: "var(--success)" },
  { tag: [t.number, t.bool, t.null], color: "var(--warning)" },
  { tag: t.comment, color: "var(--fg-subtle)", fontStyle: "italic" },
  { tag: [t.operator, t.punctuation], color: "var(--fg-muted)" },
  { tag: [t.typeName, t.standard(t.name)], color: "var(--chart-4)" },
  { tag: t.special(t.name), color: "var(--chart-2)" },
]);

const theme = EditorView.theme({
  "&": { color: "var(--fg)", backgroundColor: "var(--surface)" },
  ".cm-content": { caretColor: "var(--accent)", padding: "10px 0" },
  ".cm-cursor": { borderLeftColor: "var(--accent)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "color-mix(in srgb, var(--accent) 22%, transparent) !important",
  },
});

export function SqlEditor({
  value,
  onChange,
  onRun,
  schema,
  ariaLabel = "SQL editor",
}: {
  value: string;
  onChange: (v: string) => void;
  onRun: () => void;
  schema: Record<string, string[]>;
  ariaLabel?: string;
}) {
  const extensions = useMemo(
    () => [
      sql({ dialect: PostgreSQL, schema, upperCaseKeywords: true }),
      syntaxHighlighting(highlight),
      theme,
      EditorView.lineWrapping,
      EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
      Prec.highest(
        keymap.of([
          {
            key: "Mod-Enter",
            run: () => {
              onRun();
              return true;
            },
          },
        ]),
      ),
    ],
    [schema, onRun, ariaLabel],
  );
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      theme="none"
      height="100%"
      className="h-full"
      basicSetup={{ foldGutter: false, highlightActiveLineGutter: true, autocompletion: true, bracketMatching: true }}
      data-testid="sql-editor"
    />
  );
}
