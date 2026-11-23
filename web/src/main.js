import { mount } from 'svelte'
import './app.css'
import './cf.css'
import './themes.css'
import './ui.css'
import './motion.css'
import App from './App.svelte'

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
