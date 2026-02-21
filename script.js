(function () {
  'use strict';

  var REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  var DATA_URL = 'data/total.json';

  var odometerEl = document.getElementById('odometer');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');
  var breakdownEl = document.getElementById('breakdown');

  var hasLoadedOnce = false;
  var drumWrappers = [];
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

  function getDigitHeight(wrapper) {
    var cell = wrapper.querySelector('.drum-digit');
    if (!cell) return 88;
    return cell.offsetHeight || 88;
  }

  function setDrumDigit(wrapper, digit, animate) {
    var drum = wrapper._drum;
    if (!drum) return;

    var h = getDigitHeight(wrapper);
    var offset = -(digit * h);

    if (!animate) {
      drum.style.transition = 'none';
      drum.style.webkitTransition = 'none';
      drum.style.transform = 'translateY(' + offset + 'px)';
      drum.style.webkitTransform = 'translateY(' + offset + 'px)';
      void drum.offsetHeight;
      drum.style.transition = '';
      drum.style.webkitTransition = '';
    } else {
      drum.style.transform = 'translateY(' + offset + 'px)';
      drum.style.webkitTransform = 'translateY(' + offset + 'px)';
    }

    wrapper._currentDigit = digit;
  }

  function createDrum() {
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
    wrapper._currentDigit = 0;

    return wrapper;
  }

  // Build odometer at all zeros, then roll up to target digits
  function buildOdometer(formatted, animateIn) {
    odometerEl.innerHTML = '';
    drumWrappers = [];

    var dollarEl = document.createElement('span');
    dollarEl.className = 'sep dollar-sign';
    dollarEl.textContent = '$';
    odometerEl.appendChild(dollarEl);

    var targetDigits = [];

    for (var i = 0; i < formatted.length; i++) {
      var ch = formatted[i];

      if (ch === ',' || ch === '.') {
        var sepEl = document.createElement('span');
        sepEl.className = 'sep' + (ch === '.' ? ' period' : '');
        sepEl.textContent = ch;
        odometerEl.appendChild(sepEl);
      } else {
        var digit = parseInt(ch, 10);
        var wrapper = createDrum();
        odometerEl.appendChild(wrapper);
        drumWrappers.push(wrapper);
        targetDigits.push(digit);
      }
    }

    lastFormattedStr = formatted;

    // After DOM layout: set to 0, then roll to target
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        // First, ensure all drums are at 0
        for (var j = 0; j < drumWrappers.length; j++) {
          setDrumDigit(drumWrappers[j], 0, false);
        }

        if (animateIn) {
          // Roll to target digits with staggered delays
          // Right-to-left stagger (cents first, like a real odometer counting)
          setTimeout(function () {
            for (var k = drumWrappers.length - 1; k >= 0; k--) {
              if (targetDigits[k] !== 0) {
                rollToDigit(drumWrappers[k], targetDigits[k], (drumWrappers.length - 1 - k) * 120);
              }
            }
          }, 300);
        } else {
          for (var k = 0; k < drumWrappers.length; k++) {
            setDrumDigit(drumWrappers[k], targetDigits[k], false);
          }
        }
      });
    });
  }

  // Roll a single drum to a digit with delay, duration proportional to distance
  function rollToDigit(wrapper, digit, delay) {
    setTimeout(function () {
      var distance = Math.abs(digit - wrapper._currentDigit);
      // More distance = longer roll, with slight random variation
      var baseDuration = 0.6 + (distance * 0.15);
      var jitter = (Math.random() - 0.5) * 0.2;
      var duration = baseDuration + jitter;

      var drum = wrapper._drum;
      drum.style.transitionDuration = duration + 's';
      drum.style.webkitTransitionDuration = duration + 's';
      // Slightly different easing per drum for mechanical feel
      var overshoot = 'cubic-bezier(0.2, 0.6, 0.35, 1.0)';
      drum.style.transitionTimingFunction = overshoot;
      drum.style.webkitTransitionTimingFunction = overshoot;

      setDrumDigit(wrapper, digit, true);
    }, delay);
  }

  function extractDigits(str) {
    return str.replace(/[^0-9]/g, '');
  }

  function updateOdometer(usd) {
    var formatted = formatAmount(usd);

    var newDigitCount = extractDigits(formatted).length;
    var oldDigitCount = extractDigits(lastFormattedStr).length;

    // First load or digit count changed: build fresh with roll-up animation
    if (drumWrappers.length === 0 || newDigitCount !== oldDigitCount) {
      buildOdometer(formatted, !hasLoadedOnce || newDigitCount !== oldDigitCount);
      return;
    }

    // Subsequent updates: roll changed drums
    var newDigits = extractDigits(formatted);
    var delay = 0;

    for (var i = 0; i < drumWrappers.length; i++) {
      var newDigit = parseInt(newDigits[i], 10);

      if (drumWrappers[i]._currentDigit !== newDigit) {
        rollToDigit(drumWrappers[i], newDigit, delay);
        delay += 80;
      }
    }

    lastFormattedStr = formatted;
  }

  function formatLastUpdated(isoString) {
    try {
      var d = new Date(isoString);
      var opts = { timeZone: 'America/New_York' };
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      // Extract Eastern-Time components
      var parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        month: 'numeric', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
        hour12: true
      }).formatToParts(d);
      var p = {};
      parts.forEach(function (x) { p[x.type] = x.value; });
      var month = months[parseInt(p.month, 10) - 1];
      return 'Running total \u00b7 Updated ' + month + ' ' + p.day + ', ' + p.hour + ':' + p.minute + ' ' + p.dayPeriod + ' ET';
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

        // Show PAC/bundler breakdown if bundler data exists
        if (breakdownEl && data.bundler_usd > 0) {
          var pacStr = '$' + Math.round(data.pac_usd || 0).toLocaleString('en-US');
          var bundlerStr = '$' + Math.round(data.bundler_usd).toLocaleString('en-US');
          breakdownEl.innerHTML =
            '<span class="bd-pac">PACs: ' + pacStr + '</span>' +
            '<span class="bd-sep">\u00b7</span>' +
            '<span class="bd-bundler">Bundlers: ' + bundlerStr + '</span>';
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
