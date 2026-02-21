(function () {
  'use strict';

  var DATA_URL = 'data/candidates.json';
  var listEl = document.getElementById('race-list');
  var searchEl = document.getElementById('search');
  var stateFilterEl = document.getElementById('state-filter');
  var chamberFilterEl = document.getElementById('chamber-filter');
  var countEl = document.getElementById('results-count');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');
  var emptyEl = document.getElementById('empty');

  var allRaces = [];

  var STATE_NAMES = {
    AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',
    CO:'Colorado',CT:'Connecticut',DE:'Delaware',FL:'Florida',GA:'Georgia',
    HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',
    KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',
    MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',
    MT:'Montana',NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',
    NM:'New Mexico',NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',
    OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',
    SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',
    VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming',
    DC:'District of Columbia',PR:'Puerto Rico',GU:'Guam',VI:'Virgin Islands',
    AS:'American Samoa',MP:'Northern Mariana Islands'
  };

  var OFFICE_LABELS = { H: 'House', S: 'Senate', P: 'President' };
  var PARTY_LABELS = { DEM: 'D', REP: 'R', LIB: 'L', GRE: 'G', IND: 'I' };

  function formatMoney(n) {
    return '$' + n.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function raceKey(c) {
    if (c.office === 'P') return 'P::US::00';
    var district = c.district || '00';
    return (c.office || '') + '::' + (c.state || '') + '::' + district;
  }

  function raceLabel(race) {
    if (race.office === 'P') return 'President';
    var stateName = STATE_NAMES[race.state] || race.state;
    if (race.office === 'S') return stateName + ' Senate';
    if (race.office === 'H') {
      var d = race.district && race.district !== '00' ? race.district : 'At-Large';
      return stateName + ' \u2013 District ' + d;
    }
    return stateName;
  }

  function raceShortLabel(race) {
    if (race.office === 'P') return 'President';
    if (race.office === 'S') return race.state + ' Senate';
    if (race.office === 'H') {
      var d = race.district && race.district !== '00' ? race.district : 'AL';
      return race.state + '-' + d;
    }
    return race.state;
  }

  function groupIntoRaces(candidates) {
    var map = {};
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      var key = raceKey(c);
      if (!map[key]) {
        map[key] = {
          office: c.office,
          state: c.state || 'US',
          district: c.district || '00',
          total: 0,
          candidates: []
        };
      }
      map[key].total += c.total;
      map[key].candidates.push(c);
    }
    var races = [];
    for (var k in map) {
      if (map.hasOwnProperty(k)) {
        map[k].candidates.sort(function (a, b) { return b.total - a.total; });
        races.push(map[k]);
      }
    }
    races.sort(function (a, b) { return b.total - a.total; });
    return races;
  }

  function partyClass(party) {
    if (['DEM','REP','LIB','GRE','IND'].indexOf(party) !== -1) return 'party-' + party;
    return 'party-other';
  }

  function officeClass(office) {
    return 'office-' + (office || 'H');
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function buildList(races) {
    listEl.innerHTML = '';

    if (races.length === 0) {
      emptyEl.style.display = 'block';
      countEl.textContent = '';
      return;
    }
    emptyEl.style.display = 'none';

    var grandTotal = 0;
    for (var t = 0; t < races.length; t++) grandTotal += races[t].total;
    countEl.textContent = races.length + ' race' + (races.length !== 1 ? 's' : '') +
      ' \u00b7 ' + formatMoney(grandTotal) + ' total';

    for (var i = 0; i < races.length; i++) {
      var r = races[i];
      var li = document.createElement('li');
      li.className = 'race-item';

      var officeBadge = '<span class="office-badge ' + officeClass(r.office) + '">' +
        (OFFICE_LABELS[r.office] || r.office) + '</span>';

      var row = document.createElement('div');
      row.className = 'race-row';
      row.innerHTML =
        '<span class="rank">' + (i + 1) + '</span>' +
        '<div class="race-info">' +
          '<div class="race-label">' + officeBadge + escapeHtml(raceLabel(r)) + '</div>' +
          '<div class="race-meta">' + r.candidates.length + ' candidate' +
            (r.candidates.length !== 1 ? 's' : '') + ' receiving funds</div>' +
        '</div>' +
        '<span class="race-amount">' + formatMoney(r.total) + '</span>' +
        '<span class="expand-icon">&#9656;</span>';

      row.addEventListener('click', (function (item) {
        return function () { item.classList.toggle('open'); };
      })(li));

      var detail = document.createElement('div');
      detail.className = 'race-detail';
      var html = '<div class="detail-title">Candidates in this race</div>';
      for (var j = 0; j < r.candidates.length; j++) {
        var c = r.candidates[j];
        var badge = c.party
          ? '<span class="party-badge ' + partyClass(c.party) + '">' +
            (PARTY_LABELS[c.party] || c.party) + '</span>'
          : '';
        html += '<div class="candidate-line">' +
          '<span class="candidate-line-name">' + badge + escapeHtml(c.name) + '</span>' +
          '<span class="cl-amount">' + formatMoney(c.total) + '</span></div>';
      }
      detail.innerHTML = html;

      li.appendChild(row);
      li.appendChild(detail);
      listEl.appendChild(li);
    }
  }

  function applyFilters() {
    var query = searchEl.value.toLowerCase().trim();
    var stateVal = stateFilterEl.value;
    var chamberVal = chamberFilterEl.value;

    var filtered = allRaces.filter(function (r) {
      if (stateVal && r.state !== stateVal) return false;
      if (chamberVal && r.office !== chamberVal) return false;
      if (query) {
        var searchable = (raceLabel(r) + ' ' + raceShortLabel(r) + ' ' +
          r.state + ' ' + (STATE_NAMES[r.state] || '')).toLowerCase();
        // Also search candidate names within the race
        for (var i = 0; i < r.candidates.length; i++) {
          searchable += ' ' + r.candidates[i].name.toLowerCase();
        }
        if (searchable.indexOf(query) === -1) return false;
      }
      return true;
    });

    buildList(filtered);
  }

  function populateStateFilter(races) {
    var states = {};
    for (var i = 0; i < races.length; i++) {
      if (races[i].state && races[i].state !== 'US') states[races[i].state] = true;
    }
    var sorted = Object.keys(states).sort();
    for (var j = 0; j < sorted.length; j++) {
      var opt = document.createElement('option');
      opt.value = sorted[j];
      opt.textContent = sorted[j] + ' \u2013 ' + (STATE_NAMES[sorted[j]] || sorted[j]);
      stateFilterEl.appendChild(opt);
    }
  }

  function formatUpdated(isoString) {
    try {
      var d = new Date(isoString);
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      var parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        month: 'numeric', day: 'numeric',
        hour: 'numeric', minute: '2-digit', hour12: true
      }).formatToParts(d);
      var p = {};
      parts.forEach(function (x) { p[x.type] = x.value; });
      var month = months[parseInt(p.month, 10) - 1];
      return 'Running total \u00b7 Updated ' + month + ' ' + p.day + ', ' + p.hour + ':' + p.minute + ' ' + p.dayPeriod + ' ET';
    } catch (e) { return ''; }
  }

  function fetchData() {
    fetch(DATA_URL + '?t=' + Date.now())
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var candidates = data.candidates || [];
        allRaces = groupIntoRaces(candidates);
        errorEl.style.display = 'none';
        populateStateFilter(allRaces);
        applyFilters();
        if (data.last_updated) {
          updatedEl.textContent = formatUpdated(data.last_updated);
        }
      })
      .catch(function (err) {
        console.error('Failed to fetch race data:', err);
        errorEl.textContent = 'Unable to load race data. Will retry shortly.';
        errorEl.style.display = 'block';
      });
  }

  searchEl.addEventListener('input', applyFilters);
  stateFilterEl.addEventListener('change', applyFilters);
  chamberFilterEl.addEventListener('change', applyFilters);

  fetchData();
})();
