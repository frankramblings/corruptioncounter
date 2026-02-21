(function () {
  'use strict';

  var DATA_URL = 'data/candidates.json';
  var listEl = document.getElementById('candidate-list');
  var searchEl = document.getElementById('search');
  var stateFilterEl = document.getElementById('state-filter');
  var officeFilterEl = document.getElementById('office-filter');
  var partyFilterEl = document.getElementById('party-filter');
  var countEl = document.getElementById('results-count');
  var updatedEl = document.getElementById('updated');
  var errorEl = document.getElementById('error');
  var emptyEl = document.getElementById('empty');

  var allCandidates = [];

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

  function partyClass(party) {
    if (['DEM','REP','LIB','GRE','IND'].indexOf(party) !== -1) return 'party-' + party;
    return 'party-other';
  }

  function candidateMeta(c) {
    var parts = [];
    if (c.office === 'H' && c.state && c.district) {
      parts.push(c.state + '-' + c.district);
    } else if (c.office === 'S' && c.state) {
      parts.push(c.state + ' Senate');
    } else if (c.office === 'P') {
      parts.push('President');
    } else if (c.state) {
      parts.push(c.state);
    }
    return parts.join(' &middot; ');
  }

  function buildList(candidates) {
    listEl.innerHTML = '';

    if (candidates.length === 0) {
      emptyEl.style.display = 'block';
      countEl.textContent = '';
      return;
    }
    emptyEl.style.display = 'none';

    var total = 0;
    for (var t = 0; t < candidates.length; t++) total += candidates[t].total;
    countEl.textContent = candidates.length + ' candidate' + (candidates.length !== 1 ? 's' : '') +
      ' \u00b7 ' + formatMoney(total) + ' total';

    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      var li = document.createElement('li');
      li.className = 'candidate-item';

      var partyBadge = c.party
        ? '<span class="party-badge ' + partyClass(c.party) + '">' + (PARTY_LABELS[c.party] || c.party) + '</span>'
        : '';

      var row = document.createElement('div');
      row.className = 'candidate-row';
      row.innerHTML =
        '<span class="rank">' + (i + 1) + '</span>' +
        '<div class="candidate-info">' +
          '<div class="candidate-name">' + partyBadge + escapeHtml(c.name) + '</div>' +
          '<div class="candidate-meta">' + candidateMeta(c) + '</div>' +
        '</div>' +
        '<span class="candidate-amount">' + formatMoney(c.total) + '</span>' +
        '<span class="expand-icon">&#9656;</span>';

      row.addEventListener('click', (function (item) {
        return function () { item.classList.toggle('open'); };
      })(li));

      var detail = document.createElement('div');
      detail.className = 'pac-detail';
      var detailHtml = '';

      // Show bundler/PAC/IE summary if bundler data exists
      if (c.bundler_total || c.pac_total || c.ie_total) {
        detailHtml += '<div class="pac-detail-title">Breakdown</div>';
        if (c.pac_total) {
          detailHtml += '<div class="pac-line"><span>PAC Contributions</span>' +
            '<span class="pac-amount">' + formatMoney(c.pac_total) + '</span></div>';
        }
        if (c.bundler_total) {
          detailHtml += '<div class="pac-line"><span>Bundlers (Pro-Israel Mega Donors)</span>' +
            '<span class="pac-amount bundler-amount">' + formatMoney(c.bundler_total) + '</span></div>';
        }
        if (c.ie_total) {
          detailHtml += '<div class="pac-line"><span>Independent Expenditures</span>' +
            '<span class="pac-amount">' + formatMoney(c.ie_total) + '</span></div>';
        }
        detailHtml += '<div class="pac-detail-divider"></div>';
      }

      detailHtml += '<div class="pac-detail-title">Contributing PACs</div>';
      var pacs = c.pacs || [];
      for (var j = 0; j < pacs.length; j++) {
        detailHtml += '<div class="pac-line"><span>' + escapeHtml(pacs[j].name) + '</span>' +
          '<span class="pac-amount">' + formatMoney(pacs[j].amount) + '</span></div>';
      }
      if (pacs.length === 0) {
        detailHtml += '<div class="pac-line"><span class="no-data">No direct PAC contributions</span></div>';
      }
      detail.innerHTML = detailHtml;

      li.appendChild(row);
      li.appendChild(detail);
      listEl.appendChild(li);
    }
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function applyFilters() {
    var query = searchEl.value.toLowerCase().trim();
    var stateVal = stateFilterEl.value;
    var officeVal = officeFilterEl.value;
    var partyVal = partyFilterEl.value;

    var filtered = allCandidates.filter(function (c) {
      if (stateVal && c.state !== stateVal) return false;
      if (officeVal && c.office !== officeVal) return false;
      if (partyVal && c.party !== partyVal) return false;
      if (query) {
        var searchable = (c.name + ' ' + c.state + ' ' + (STATE_NAMES[c.state] || '') +
          ' ' + (c.district || '')).toLowerCase();
        if (searchable.indexOf(query) === -1) return false;
      }
      return true;
    });

    buildList(filtered);
  }

  function populateStateFilter(candidates) {
    var states = {};
    for (var i = 0; i < candidates.length; i++) {
      if (candidates[i].state) states[candidates[i].state] = true;
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
        allCandidates = data.candidates || [];
        errorEl.style.display = 'none';
        populateStateFilter(allCandidates);
        applyFilters();
        if (data.last_updated) {
          updatedEl.textContent = formatUpdated(data.last_updated);
        }
      })
      .catch(function (err) {
        console.error('Failed to fetch candidates:', err);
        errorEl.textContent = 'Unable to load candidate data. Will retry shortly.';
        errorEl.style.display = 'block';
      });
  }

  searchEl.addEventListener('input', applyFilters);
  stateFilterEl.addEventListener('change', applyFilters);
  officeFilterEl.addEventListener('change', applyFilters);
  partyFilterEl.addEventListener('change', applyFilters);

  fetchData();
})();
