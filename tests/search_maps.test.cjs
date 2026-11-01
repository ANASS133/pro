const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { JSDOM } = require('../ai-job-autofill/server/node_modules/jsdom');

function setup(url = 'http://localhost/') {
    const dom = new JSDOM(`<select id="search_source_1" name="source" form="search_form_1"><option value="all">All</option><option value="job_portals">Jobs</option><option value="google_maps">Maps</option></select>
        <div id="search-jobs-workspace"><form id="search_form_1"><input id="keyword" value="IT"><input id="location" value="Berlin"></form></div>
        <div id="search-maps-workspace" hidden><input id="gmaps-query"></div>`, { url, runScripts: 'outside-only' });
    const { window } = dom;
    window.eval(readFileSync('static/spa/sections/google-maps.js', 'utf8'));
    const calls = { show: 0, hide: 0, created: 0 };
    window.SPASections.createGoogleMapsSection = () => {
        calls.created++;
        return { show() { calls.show++; }, hide() { calls.hide++; } };
    };
    const controller = window.SPASections.createSearchSources();
    const source = window.document.getElementById('search_source_1');
    const select = value => { source.value = value; source.dispatchEvent(new window.Event('change')); };
    return { window, controller, source, calls, select, close: () => window.close() };
}

test('legacy redirect query opens Maps within Search', () => {
    const s = setup('http://localhost/?source=google_maps');
    s.controller.show();
    assert.equal(s.source.value, 'google_maps');
    assert.equal(s.window.document.getElementById('search-maps-workspace').hidden, false);
    assert.equal(s.window.document.getElementById('search-jobs-workspace').hidden, true);
    assert.equal(s.calls.show, 1);
    s.close();
});

test('switching sources preserves queries and reuses one Maps controller', () => {
    const s = setup(); s.controller.show(); s.select('google_maps');
    const query = s.window.document.getElementById('gmaps-query');
    assert.equal(query.value, 'IT Berlin');
    query.value = 'Dentists Hamburg';
    s.select('job_portals');
    assert.equal(s.window.document.getElementById('search-maps-workspace').hidden, true);
    assert.equal(s.window.document.getElementById('search-jobs-workspace').hidden, false);
    s.select('google_maps');
    assert.equal(query.value, 'Dentists Hamburg');
    assert.equal(s.calls.created, 1);
    assert.equal(new URL(s.window.location.href).searchParams.get('source'), 'google_maps');
    s.close();
});

test('returning from another section resumes the selected workspace', () => {
    const s = setup('http://localhost/?source=google_maps');
    s.controller.show(); s.controller.hide(); s.controller.show();
    assert.equal(s.calls.show, 2); assert.equal(s.calls.hide, 1);
    s.close();
});

test('source outside the form remains part of search submission', () => {
    const s = setup(); s.controller.show(); s.select('job_portals');
    const data = new s.window.FormData(s.window.document.getElementById('search_form_1'));
    assert.equal(data.get('source'), 'job_portals');
    s.close();
});
