(function () {
  'use strict';

  var REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  var DATA_URL = 'data/total.json';

  var odometerEl = document.getElementById('odometer');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');

  var hasLoadedOnce = false;
  var drumWrappers = []; // only the actual drum wrappers (not separators)
  var lastFormattedStr = '';

  function splitAmount(usd) {
    var val = Math.max(0, usd);
    var fixed = val.toFixed(2);
    var parts = fixed.split('.');
    return { whole: parts[0], cents: parts[1] };
  }

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

  function formatAmount(usd) {
    var parts = splitAmount(usd);
    return addCommas(parts.whole) + '.' + parts.cents;
  }

  // Measure the pixel height of one digit cell inside a drum wrapper
  function getDigitHeight(wrapper) {
    var cell = wrapper.querySelector('.drum-digit');
    if (!cell) return 88; // fallback
    return cell.offsetHeight || 88;
  }

  // Set a drum to show a specific digit (0-9), optionally without animation
  function setDrumDigit(wrapper, digit, animate) {
    var drum = wrapper._drum;
    if (!drum) return;

    var h = getDigitHeight(wrapper);
    var offset = -(digit * h);

    if (!animate) {
      // Disable transitions, set position, force layout, re-enable
      drum.style.transition = 'none';
      drum.style.webkitTransition = 'none';
      drum.style.transform = 'translateY(' + offset + 'px)';
      drum.style.webkitTransform = 'translateY(' + offset + 'px)';
      // Force synchronous layout recalc
      void drum.offsetHeight;
      // Re-enable transitions
      drum.style.transition = '';
      drum.style.webkitTransition = '';
    } else {
      drum.style.transform = 'translateY(' + offset + 'px)';
      drum.style.webkitTransform = 'translateY(' + offset + 'px)';
    }

    wrapper._currentDigit = digit;
  }

  // Create a single drum element with digits 0-9
  function createDrum(initialDigit) {
    var wrapper = document.createElement('div');
    wrapper.className = 'drum-wrapper';

    var drum = document.createElement('div');
    drum.className = 'drum';

    for (var d = 0; d <= 9; d++) {
      var cell = document.createElement('div');
      cell.className = 'drum-digit';
      cell.textContent = d;
      drum.appendChild(cell);
    }

    wrapper.appendChild(drum);
    wrapper._drum = drum;
    wrapper._currentDigit = initialDigit;

    return wrapper;
  }

  // Build the full odometer display for a formatted string like "1,234.56"
  function buildOdometer(formatted) {
    odometerEl.innerHTML = '';
    drumWrappers = [];

    // Dollar sign
    var dollarEl = document.createElement('span');
    dollarEl.className = 'sep dollar-sign';
    dollarEl.textContent = '$';
    odometerEl.appendChild(dollarEl);

    // Temporary array to hold drums that need initial positioning
    var drumsToInit = [];

    for (var i = 0; i < formatted.length; i++) {
      var ch = formatted[i];

      if (ch === ',' || ch === '.') {
        var sepEl = document.createElement('span');
        sepEl.className = 'sep' + (ch === '.' ? ' period' : '');
        sepEl.textContent = ch;
        odometerEl.appendChild(sepEl);
      } else {
        var digit = parseInt(ch, 10);
        var wrapper = createDrum(digit);
        odometerEl.appendChild(wrapper);
        drumWrappers.push(wrapper);
        drumsToInit.push({ wrapper: wrapper, digit: digit });
      }
    }

    lastFormattedStr = formatted;

    // Position drums after DOM has been laid out so offsetHeight is accurate.
    // Use a double-rAF to guarantee the browser has painted.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        for (var j = 0; j < drumsToInit.length; j++) {
          setDrumDigit(drumsToInit[j].wrapper, drumsToInit[j].digit, false);
        }
      });
    });
  }

  // Extract just the digit characters from a formatted string
  function extractDigits(str) {
    return str.replace(/[^0-9]/g, '');
  }

  // Update odometer to a new USD value
  function updateOdometer(usd) {
    var formatted = formatAmount(usd);

    // If structure changed (different number of digits), rebuild
    var newDigitCount = extractDigits(formatted).length;
    var oldDigitCount = extractDigits(lastFormattedStr).length;

    if (drumWrappers.length === 0 || newDigitCount !== oldDigitCount) {
      buildOdometer(formatted);
      return;
    }

    // Roll individual drums to new values
    var newDigits = extractDigits(formatted);
    var delay = 0;

    for (var i = 0; i < drumWrappers.length; i++) {
      var wrapper = drumWrappers[i];
      var newDigit = parseInt(newDigits[i], 10);

      if (wrapper._currentDigit !== newDigit) {
        (function (w, d, dl) {
          setTimeout(function () {
            // Add slight timing variation for mechanical feel
            var extra = Math.random() * 200;
            var drum = w._drum;
            drum.style.transitionDuration = (0.8 + extra / 1000) + 's';
            drum.style.webkitTransitionDuration = (0.8 + extra / 1000) + 's';
            setDrumDigit(w, d, true);
          }, dl);
        })(wrapper, newDigit, delay);
        delay += 80;
      }
    }

    lastFormattedStr = formatted;
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
          updateOdometer(0);
        }
        errorEl.textContent = 'Unable to load latest data. Will retry shortly.';
        errorEl.style.display = 'block';
      });
  }

  fetchTotal();
  setInterval(fetchTotal, REFRESH_INTERVAL_MS);
})();
