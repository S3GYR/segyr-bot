import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const API_TOKEN = import.meta.env.VITE_API_TOKEN || 'segyr-token'

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Token': API_TOKEN,
  },
})

export const fetchDashboard = () => client.get('/dashboard/data').then((r) => r.data)
export const fetchChantiers = () => client.get('/chantier').then((r) => r.data)
export const fetchFactures = () => client.get('/factures').then((r) => r.data)
export const fetchHealthFull = () => client.get('/health/full').then((r) => r.data)
export const fetchRepairStatus = (limit = 20) => client.get('/repair/status', { params: { limit } }).then((r) => r.data)
export const fetchDashboardSummary = (limit = 20) => client.get('/dashboard/summary', { params: { limit } }).then((r) => r.data)
export const runRepair = () => client.post('/repair/run').then((r) => r.data)
export const runRepairDryRun = () => client.post('/repair/dry-run').then((r) => r.data)
export const relanceFacture = (factureId) =>
  client.post('/chat', { message: `Relance facture ${factureId}` }).then((r) => r.data)

export default client
