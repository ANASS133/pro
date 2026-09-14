const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

function setup(count = 1) {
    let now = 0;
    let nextId = 0;
    const timers = new Map();
    const observers = [];
    const buttons = Array.from({ length: count }, () => ({
        visible: false, isConnected: true, disabled: false, clicks: 0,
        getClientRects() { return this.visible ? [{}] : []; },
        addEventListener(_event, callback) { this.onClick = callback; },
        click() { this.onClick(); this.clicks++; },
    }));
    vm.runInNewContext(readFileSync('static/auto_continue.js', 'utf8'), {
        document: { querySelectorAll: () => buttons },
        window: { addEventListener() {} },
        getComputedStyle: () => ({ visibility: 'visible' }),
        MutationObserver: class {
            constructor(callback) { observers.push(callback); }
            observe() {}
        },
        setTimeout(callback, delay) {
            timers.set(++nextId, { callback, deadline: now + delay });
            return nextId;
        },
        clearTimeout: (id) => timers.delete(id),
    });
    return {
        buttons,
        update() { observers.forEach((callback) => callback()); },
        tick(ms) {
            now += ms;
            for (const [id, timer] of timers) {
                if (timer.deadline <= now) {
                    timers.delete(id);
                    timer.callback();
                }
            }
        },
    };
}

test('clicks once after five seconds despite repeated status updates', () => {
    const ui = setup();
    ui.buttons[0].visible = true;
    ui.update();
    ui.tick(3000);
    ui.update();
    ui.tick(1999);
    assert.equal(ui.buttons[0].clicks, 0);
    ui.tick(1);
    assert.equal(ui.buttons[0].clicks, 1);
    ui.update();
    ui.tick(10000);
    assert.equal(ui.buttons[0].clicks, 1);
});

test('manual click cancels automatic click until the next appearance', () => {
    const ui = setup();
    const button = ui.buttons[0];
    button.visible = true;
    ui.update();
    ui.tick(2000);
    button.click();
    ui.update();
    ui.tick(5000);
    assert.equal(button.clicks, 1);
    button.visible = false;
    ui.update();
    button.visible = true;
    ui.update();
    ui.tick(5000);
    assert.equal(button.clicks, 2);
});

test('hiding a button cancels its timer without affecting another button', () => {
    const ui = setup(2);
    ui.buttons.forEach((button) => { button.visible = true; });
    ui.update();
    ui.tick(2000);
    ui.buttons[0].visible = false;
    ui.update();
    ui.tick(3000);
    assert.deepEqual(ui.buttons.map((button) => button.clicks), [0, 1]);
});

test('checks visibility and disabled state again before clicking', () => {
    for (const change of [b => { b.visible = false; }, b => { b.disabled = true; }]) {
        const ui = setup();
        ui.buttons[0].visible = true;
        ui.update();
        change(ui.buttons[0]);
        ui.tick(5000);
        assert.equal(ui.buttons[0].clicks, 0);
    }
});
