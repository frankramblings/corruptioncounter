(function () {
  'use strict';

  var REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  var DATA_URL = 'data/total.json';

  var odometerEl = document.getElementById('odometer');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');

  var hasLoadedOnce = false;
  var currentDigits = [];
  var drumElements = [];

  // Format a dollar amount (in USD float) into parts: digits + separator positions
  // Returns e.g. { whole: "1234567", cents: "89" } for 1234567.89
  function splitAmount(usd) {
    var val = Math.max(0, usd);
    var fixed = val.toFixed(2);
    var parts = fixed.split('.');
    return { whole: parts[0], cents: parts[1] };
  }

  // Format whole part with commas: "1234567" -> "1,234,567"
  function addCommas(str) {
    var result = [];
    var count = 0;
    for (var i = str.length - 1; i >= 0; i--) {
      if (count > 0 && count % 3 === 0) {
        result.unshift(',');
      }
      result.unshift(str[i]);
      count++;
    }
    return result.join('');
  }

  // Build the odometer DOM: $ sign, digit drums, commas, period, cent drums
  // displayStr is like "1,234,567.89"
  function buildOdometer(displayStr) {
    odometerEl.innerHTML = '';
    drumElements = [];
    currentDigits = [];

    // Dollar sign
    var dollarEl = document.createElement('span');
    dollarEl.className = 'sep dollar-sign';
    dollarEl.textContent = '$';
    odometerEl.appendChild(dollarEl);

    for (var i = 0; i < displayStr.length; i++) {
      var ch = displayStr[i];

      if (ch === ',' || ch === '.') {
        var sepEl = document.createElement('span');
        sepEl.className = 'sep' + (ch === '.' ? ' period' : '');
        sepEl.textContent = ch;
        odometerEl.appendChild(sepEl);
        drumElements.push(null); // placeholder so indices align
        currentDigits.push(ch);
      } else {
        var digit = parseInt(ch, 10);
        var wrapper = createDrum(digit);
        odometerEl.appendChild(wrapper);
        drumElements.push(wrapper);
        currentDigits.push(digit);
      }
    }
  }

  // Create a single drum wrapper with digits 0-9 stacked vertically
  function createDrum(initialDigit) {
    var wrapper = document.createElement('div');
    wrapper.className = 'drum-wrapper';

    var drum = document.createElement('div');
    drum.className = 'drum';

    // We place digits 0-9 then repeat 0 at the bottom for seamless wrap
    for (var d = 0; d <= 9; d++) {
      var cell = document.createElement('div');
      cell.className = 'drum-digit';
      cell.textContent = d;
      drum.appendChild(cell);
    }

    wrapper.appendChild(drum);

    // Set to initial digit immediately (no transition)
    requestAnimationFrame(function() {
      drum.style.transition = 'none';
      drum.style.transform = 'translateY(-' + (initialDigit * 100) + '%)';
      // Force reflow then re-enable transitions
      drum.offsetHeight;
      drum.style.transition = '';
    });

    wrapper._drum = drum;
    wrapper._currentDigit = initialDigit;

    return wrapper;
  }

  // Roll a drum from its current digit to a new digit
  function rollDrum(wrapper, newDigit, delay) {
    if (!wrapper || !wrapper._drum) return;
    var drum = wrapper._drum;

    setTimeout(function() {
      // Add slight variation to timing for mechanical feel
      var extraMs = Math.random() * 200;
      drum.style.transitionDuration = (0.8 + extraMs / 1000) + 's';
      drum.style.transform = 'translateY(-' + (newDigit * 100) + '%)';
      wrapper._currentDigit = newDigit;
    }, delay);
  }

  // Update the odometer to show a new value (in USD)
  function updateOdometer(usd) {
    var parts = splitAmount(usd);
    var formatted = addCommas(parts.whole) + '.' + parts.cents;

    // If first load or format length changed, rebuild the whole thing
    if (drumElements.length === 0 || getDigitCount(formatted) !== getDigitCount(currentDisplayStr())) {
      buildOdometer(formatted);
      return;
    }

    // Otherwise, roll individual drums to new digits
    var delay = 0;
    for (var i = 0; i < formatted.length; i++) {
      var ch = formatted[i];
      if (ch === ',' || ch === '.') continue;

      var newDigit = parseInt(ch, 10);
      var wrapper = drumElements[i];
      if (wrapper && wrapper._currentDigit !== newDigit) {
        rollDrum(wrapper, newDigit, delay);
        delay += 80; // stagger each drum slightly
      }
    }

    // Update stored digits
    currentDigits = [];
    for (var j = 0; j < formatted.length; j++) {
      var c = formatted[j];
      currentDigits.push((c === ',' || c === '.') ? c : parseInt(c, 10));
    }
  }

  function currentDisplayStr() {
    return currentDigits.map(function(d) {
      return typeof d === 'number' ? String(d) : d;
    }).join('');
  }

  function getDigitCount(str) {
    return str.replace(/[^0-9]/g, '').length;
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
    var url = DATA_URL + '?t=' + Date.now();

    fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var target = typeof data.usd === 'number' ? data.usd : 0;
        errorEl.style.display = 'none';

        updateOdometer(target);
        hasLoadedOnce = true;

        if (data.last_updated) {
          updatedEl.textContent = formatLastUpdated(data.last_updated);
        }
      })
      .catch(function (err) {
        console.error('Failed to fetch total:', err);
        if (!hasLoadedOnce) {
          // Show zeroed odometer on first load failure
          updateOdometer(0);
        }
        errorEl.textContent = 'Unable to load latest data. Will retry shortly.';
        errorEl.style.display = 'block';
      });
  }

  // Initial fetch
  fetchTotal();

  // Periodic refresh
  setInterval(fetchTotal, REFRESH_INTERVAL_MS);
})();
