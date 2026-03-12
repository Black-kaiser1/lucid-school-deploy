/**
 * update_url.js
 * Run this after you get your Render URL to update all config files.
 * Usage: node update_url.js https://your-actual-url.onrender.com
 */
const fs = require('fs');
const path = require('path');

const newUrl = process.argv[2];

if (!newUrl) {
  console.log('Usage: node update_url.js https://your-app.onrender.com');
  console.log('Example: node update_url.js https://lucid-school-abc123.onrender.com');
  process.exit(1);
}

// Clean URL (no trailing slash)
const url = newUrl.replace(/\/$/, '');
const domain = url.replace('https://', '').replace('http://', '');

console.log(`\n🔧 Updating app URL to: ${url}\n`);

// 1. Update capacitor.config.json
const capConfig = JSON.parse(fs.readFileSync('capacitor.config.json', 'utf8'));
capConfig.server.url = url;
capConfig.server.allowNavigation = [domain, `*.${domain.split('.').slice(-2).join('.')}`];
fs.writeFileSync('capacitor.config.json', JSON.stringify(capConfig, null, 2));
console.log('✅ Updated capacitor.config.json');

// 2. Update web/index.html
let html = fs.readFileSync('web/index.html', 'utf8');
html = html.replace(
  /var APP_URL = '.*?';/,
  `var APP_URL = '${url}/login';`
);
fs.writeFileSync('web/index.html', html);
console.log('✅ Updated web/index.html');

console.log(`
🎉 Done! Now run:
   npx cap sync android
   npx cap open android
   Then in Android Studio: Build → Build APK
`);
