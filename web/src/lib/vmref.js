// A machine across hosts: its "ref" is its name on Arrakis, "<host>~<name>" on another
// host (OrbStack names can't contain "~"). Stores keyed by machine, routes (#infra/vm-<ref>)
// and the components take refs; vmUrl turns one into its API address.
export const vmRef = (host, name) => host && host !== 'arrakis' ? `${host}~${name}` : name;
export const vmHost = (ref) => (ref || '').includes('~') ? ref.split('~')[0] : null;
export const vmName = (ref) => (ref || '').split('~').pop();
export const vmBase = (host) => host && host !== 'arrakis' ? `/api/hosts/${encodeURIComponent(host)}/vms` : '/api/vms';
export const vmUrl = (ref, path = '') => `${vmBase(vmHost(ref))}/${encodeURIComponent(vmName(ref))}${path}`;
