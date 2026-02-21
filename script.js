(function () {
  'use strict';

  var REFRESH_INTERVAL_MS = 5 * 60 * 1000; // re-fetch every 5 minutes
  var ANIMATION_DURATION_MS = 2000;
  var DATA_URL = 'data/total.json';

  var amountEl = document.getElementById('amount');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');

  var currentDisplayValue = 0;
  var animationFrame = null;

  function formatUSD(cents) {
    // cents is an integer representing the total in cents
    // but we receive usd as a float, so we work in dollars here
    return cents.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function animateCounter(from, to, duration) {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame);
    }

    var startTime = null;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var elapsed = timestamp - startTime;
      var progress = Math.min(elapsed / duration, 1);

      // ease-out cubic
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = from + (to - from) * eased;

      currentDisplayValue = current;
      amountEl.textContent = formatUSD(current);

      if (progress < 1) {
        animationFrame = requestAnimationFrame(step);
      } else {
        currentDisplayValue = to;
        amountEl.textContent = formatUSD(to);
      }
    }

    animationFrame = requestAnimationFrame(step);
  }

  function formatLastUpdated(isoString) {
    try {
      var d = new Date(isoString);
      return 'Last updated: ' + d.toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short'
      });
    } catch (e) {
      return '';
    }
  }

  function fetchTotal() {
    // cache-bust so GitHub Pages CDN doesn't serve stale data
    var url = DATA_URL + '?t=' + Date.now();

    fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var target = typeof data.usd === 'number' ? data.usd : 0;
        errorEl.style.display = 'none';

        animateCounter(currentDisplayValue, target, ANIMATION_DURATION_MS);

        if (data.last_updated) {
          updatedEl.textContent = formatLastUpdated(data.last_updated);
        }
      })
      .catch(function (err) {
        console.error('Failed to fetch total:', err);
        errorEl.textContent = 'Unable to load latest data. Will retry shortly.';
        errorEl.style.display = 'block';
      });
  }

  // Initial fetch
  fetchTotal();

  // Periodic refresh
  setInterval(fetchTotal, REFRESH_INTERVAL_MS);
})();
