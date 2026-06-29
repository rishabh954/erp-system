import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add manifest
manifest_tag = '  <link rel="manifest" href="/manifest.json">\n'
if manifest_tag not in content:
    content = content.replace('</head>', manifest_tag + '</head>')

# Add service worker
sw_script = """
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/service-worker.js').then(function(registration) {
          console.log('ServiceWorker registration successful with scope: ', registration.scope);
        }, function(err) {
          console.log('ServiceWorker registration failed: ', err);
        });
      });
    }
  </script>
"""
if "navigator.serviceWorker.register" not in content:
    content = content.replace('</body>', sw_script + '</body>')

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated base.html with PWA tags")
