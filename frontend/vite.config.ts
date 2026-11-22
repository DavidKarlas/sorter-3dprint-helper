import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the backend runs on :8000 (uvicorn); Vite proxies the API to it.
export default defineConfig({
	plugins: [react()],
	server: {
		port: 5173,
		proxy: { '/api': 'http://127.0.0.1:8000' }
	}
});
