<script>
    // A code editor (CodeMirror 6) with syntax colours that follow the dashboard's theme:
    // keywords in the theme's accent, the rest in muted warm tones that read on every dark theme.
    import { onMount, onDestroy } from 'svelte';
    import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection } from '@codemirror/view';
    import { EditorState, Compartment } from '@codemirror/state';
    import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
    import { syntaxHighlighting, HighlightStyle, indentOnInput, bracketMatching, indentUnit } from '@codemirror/language';
    import { python } from '@codemirror/lang-python';
    import { json } from '@codemirror/lang-json';
    import { yaml } from '@codemirror/lang-yaml';
    import { tags as t } from '@lezer/highlight';

    export let value = '';
    export let path = '';             // picks the language from the extension
    export let readonly = false;
    export let onSave = null;         // ⌘S / Ctrl+S

    let host, view;
    const lang = new Compartment(), ro = new Compartment();
    const language = (p) => /\.py$/i.test(p) ? python() : /\.json$/i.test(p) ? json() : /\.ya?ml$/i.test(p) ? yaml() : [];

    const colours = HighlightStyle.define([
        { tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword], color: 'var(--accent)' },
        { tag: [t.string, t.special(t.string)], color: '#a8c58a' },
        { tag: [t.number, t.bool, t.null, t.atom], color: '#e0a86b' },
        { tag: [t.comment, t.lineComment, t.blockComment], color: 'var(--text-secondary)', fontStyle: 'italic' },
        { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: '#8fb8de' },
        { tag: [t.className, t.definition(t.className), t.typeName], color: '#d9b26f' },
        { tag: [t.propertyName], color: '#c6a7d8' },
        { tag: [t.self, t.special(t.variableName)], color: '#d98e73' },
        { tag: [t.operator, t.punctuation, t.bracket], color: 'var(--text-secondary)' },
        { tag: t.meta, color: '#d98e73' },
    ]);

    const theme = EditorView.theme({
        '&': { height: '100%', color: 'var(--text-primary)', backgroundColor: 'transparent', fontSize: '13px' },
        '.cm-scroller': { fontFamily: "'JetBrains Mono', monospace", lineHeight: '1.6' },
        '.cm-content': { padding: '12px 0', caretColor: 'var(--accent)' },
        '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--text-secondary)', border: 'none', opacity: '0.6' },
        '.cm-lineNumbers .cm-gutterElement': { padding: '0 12px 0 16px' },
        '.cm-activeLine': { backgroundColor: 'var(--highlight-3)' },
        '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--text-primary)' },
        '&.cm-focused': { outline: 'none' },
        '.cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection': { backgroundColor: 'var(--accent-soft) !important' },
        '.cm-cursor': { borderLeftColor: 'var(--accent)' },
        '.cm-matchingBracket': { backgroundColor: 'var(--highlight-15)', outline: 'none' },
    }, { dark: true });

    onMount(() => {
        view = new EditorView({
            parent: host,
            state: EditorState.create({
                doc: value,
                extensions: [
                    lineNumbers(), highlightActiveLine(), highlightActiveLineGutter(), drawSelection(),
                    history(), indentOnInput(), bracketMatching(), indentUnit.of('    '),
                    keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { onSave?.(); return true; } }, indentWithTab, ...defaultKeymap, ...historyKeymap]),
                    syntaxHighlighting(colours), theme,
                    lang.of(language(path)), ro.of(EditorState.readOnly.of(readonly)),
                    EditorView.updateListener.of((u) => { if (u.docChanged) value = u.state.doc.toString(); }),
                ],
            }),
        });
    });
    onDestroy(() => view?.destroy());

    // a new file opened (or text set from outside): replace the document
    $: if (view && value !== view.state.doc.toString()) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
    $: view && view.dispatch({ effects: [lang.reconfigure(language(path)), ro.reconfigure(EditorState.readOnly.of(readonly))] });
</script>

<div class="cm-host" bind:this={host}></div>

<style>
    .cm-host { height: 100%; min-height: 0; }
</style>
