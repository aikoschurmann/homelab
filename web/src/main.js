import { mount } from 'svelte'
import './app.css'
import './cf.css'
import './themes.css'
import './ui.css'
import './motion.css'
import { loadServer } from './lib/server.js'

// Who this server is comes first: modules read its name when they load, so the app is
// imported only after it's known. A server that hasn't been set up shows the setup screen
// (so does /?setup, to run it again).
const server = await loadServer()
const setup = !server.setup_done || new URLSearchParams(location.search).has('setup')
const { default: Root } = setup ? await import('./components/Setup.svelte') : await import('./App.svelte')

export default mount(Root, { target: document.getElementById('app') })
