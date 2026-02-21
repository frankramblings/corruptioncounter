(function () {
  'use strict';

  var DATA_URL = 'data/candidates.json';
  var IE_DATA_URL = 'data/independent_expenditures.json';
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
  var ieByCandidate = {};  // candidate_id -> {support, oppose, total, committees}

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

  function getCandidateGrandTotal(c) {
    var ie = ieByCandidate[c.candidate_id] || null;
    var ieTotal = ie ? ie.total : 0;
    return c.total + ieTotal;
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
    for (var t = 0; t < candidates.length; t++) total += getCandidateGrandTotal(candidates[t]);
    countEl.textContent = candidates.length + ' candidate' + (candidates.length !== 1 ? 's' : '') +
      ' \u00b7 ' + formatMoney(total) + ' total';

    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      var grandTotal = getCandidateGrandTotal(c);
      var ie = ieByCandidate[c.candidate_id] || null;
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
        '<span class="candidate-amount">' + formatMoney(grandTotal) + '</span>' +
        '<span class="expand-icon">&#9656;</span>';

      row.addEventListener('click', (function (item) {
        return function () { item.classList.toggle('open'); };
      })(li));

      var detail = document.createElement('div');
      detail.className = 'pac-detail';

      // Direct contributions section
      var pacHtml = '<div class="pac-detail-title">Direct Contributions &middot; ' + formatMoney(c.total) + '</div>';
      var pacs = c.pacs || [];
      for (var j = 0; j < pacs.length; j++) {
        pacHtml += '<div class="pac-line"><span>' + escapeHtml(pacs[j].name) + '</span>' +
          '<span class="pac-amount">' + formatMoney(pacs[j].amount) + '</span></div>';
      }

      // Independent expenditures section
      if (ie && ie.total > 0) {
        pacHtml += '<div class="pac-detail-title ie-title">Independent Expenditures &middot; ' + formatMoney(ie.total) + '</div>';
        if (ie.support > 0) {
          pacHtml += '<div class="pac-line ie-support"><span>Supporting</span>' +
            '<span class="pac-amount">' + formatMoney(ie.support) + '</span></div>';
        }
        if (ie.oppose > 0) {
          pacHtml += '<div class="pac-line ie-oppose"><span>Opposing</span>' +
            '<span class="pac-amount">' + formatMoney(ie.oppose) + '</span></div>';
        }
        var comms = ie.committees || [];
        for (var k = 0; k < comms.length; k++) {
          var commTotal = comms[k].support + comms[k].oppose;
          pacHtml += '<div class="pac-line"><span>' + escapeHtml(comms[k].name) + '</span>' +
            '<span class="pac-amount">' + formatMoney(commTotal) + '</span></div>';
        }
      }

      detail.innerHTML = pacHtml;

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
    var candidatesPromise = fetch(DATA_URL + '?t=' + Date.now())
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });

    var iePromise = fetch(IE_DATA_URL + '?t=' + Date.now())
      .then(function (res) {
        if (!res.ok) return { candidates: [] };
        return res.json();
      })
      .catch(function () { return { candidates: [] }; });

    Promise.all([candidatesPromise, iePromise])
      .then(function (results) {
        var data = results[0];
        var ieData = results[1];

        // Build IE lookup by candidate_id
        ieByCandidate = {};
        var ieCandidates = ieData.candidates || [];
        for (var i = 0; i < ieCandidates.length; i++) {
          var ic = ieCandidates[i];
          ieByCandidate[ic.candidate_id] = ic;
        }

        // Start with direct contribution candidates
        allCandidates = data.candidates || [];

        // Build set of candidate_ids already in the direct contributions list
        var directCandIds = {};
        for (var j = 0; j < allCandidates.length; j++) {
          if (allCandidates[j].candidate_id) {
            directCandIds[allCandidates[j].candidate_id] = true;
          }
        }

        // Add IE-only candidates (those not receiving direct contributions)
        for (var k = 0; k < ieCandidates.length; k++) {
          var ic2 = ieCandidates[k];
          if (!directCandIds[ic2.candidate_id]) {
            allCandidates.push({
              name: ic2.name,
              party: ic2.party,
              state: ic2.state,
              office: ic2.office,
              district: ic2.district,
              total: 0,
              candidate_id: ic2.candidate_id,
              pacs: [],
            });
          }
        }

        // Re-sort by grand total (direct + IE)
        allCandidates.sort(function (a, b) {
          return getCandidateGrandTotal(b) - getCandidateGrandTotal(a);
        });

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
