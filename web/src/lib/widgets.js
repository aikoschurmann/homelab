import { writable } from 'svelte/store';

// Overview cards the page's "Customize" menu can show or hide, one entry per card
export const OVERVIEW_WIDGETS = [
    { id: 'webapps', label: 'Web apps' },
    { id: 'attention', label: 'Updates, apps and backups' },
    { id: 'host', label: 'Cluster: totals and hosts' },
    { id: 'tailscale', label: 'Tailscale' },
    { id: 'shortcuts', label: 'Databases, terminal' },
    { id: 'compute', label: 'Compute pools' },
    { id: 'api-latency', label: 'API latency' },
];

// v2: the old ids grouped unrelated cards together
const KEY = 'overview_hidden_widgets_v2';

function load() {
    try { return new Set(JSON.parse(localStorage.getItem(KEY)) || []); } catch (e) { return new Set(); }
}

export const hiddenWidgets = writable(load());

hiddenWidgets.subscribe(set => {
    try { localStorage.setItem(KEY, JSON.stringify([...set])); } catch (e) {}
});

export function toggleWidget(id) {
    hiddenWidgets.update(set => {
        const next = new Set(set);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
    });
}

export const showAllWidgets = () => hiddenWidgets.set(new Set());
