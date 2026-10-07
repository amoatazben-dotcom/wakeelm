import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',use:{baseURL:'http://127.0.0.1:4173',headless:true,
 launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--no-sandbox']}},
 webServer:{command:'npm run dev -- --port 4173',url:'http://127.0.0.1:4173/admin-web/',reuseExistingServer:false}});
