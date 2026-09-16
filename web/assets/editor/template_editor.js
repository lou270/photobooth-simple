/*
 * Template design editor.
 *
 * A template is designed as levels, bottom first, each holding elements:
 * images, shapes and fixed text for the decoration, photo slots, and
 * variable texts ({event}, {date}, {time}) the booth fills at each photo.
 *
 * The design is the source of truth. Fabric only draws it and reports what
 * the pointer did, which is read back into the design before the canvas is
 * drawn again. Saving flattens every run of decoration between two photo
 * slots or variable texts into one transparent image, at 600 dpi, so the
 * booth only ever stacks images, photos and texts, and prints what is shown
 * here without knowing about shapes, fonts or rotation.
 */
(() => {
    'use strict';

    const CONFIG = window.EDITOR_CONFIG;
    const I18N = CONFIG.i18n;

    const TEMPLATE_DPI = 300;
    // Decoration is flattened at twice the template's resolution: the booth
    // assembles at 600 dpi when asked to, and scales down for everything else.
    const FLATTEN_SCALE = 2;
    // Browsers refuse canvases much past this on a side.
    const MAX_CANVAS_SIDE = 16000;
    const HISTORY_LIMIT = 100;
    const SNAP_DISTANCE = 6;
    const MIN_BOX = 20;
    const TEXT_LINE_SPACING = 0.15;
    const PRESET_FORMATS = {
        '10x15': { long: 1800, short: 1200 },
        '5x15': { long: 1800, short: 600 },
    };
    const PRINT_10X15 = { PageSize: 'w288h432', 'print-scaling': 'fit' };
    const PRINT_STRIP = { PageSize: 'w288h432-div2', 'print-scaling': 'fit' };
    const SLOT_KINDS = ['photo', 'field'];
    const ELEMENT_KINDS = ['image', 'rect', 'ellipse', 'line', 'label', 'photo', 'field'];

    const ICONS = {
        undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
        redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
        image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
        rect: '<rect x="3" y="5" width="18" height="14" rx="2"/>',
        ellipse: '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
        line: '<path d="M4 20 20 4"/>',
        label: '<path d="M4 7V5h16v2"/><path d="M12 5v14"/><path d="M9 19h6"/>',
        photo: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
        field: '<path d="M8 4c-2 0-3 1-3 3v2c0 1.5-1 3-2 3 1 0 2 1.5 2 3v2c0 2 1 3 3 3"/><path d="M16 4c2 0 3 1 3 3v2c0 1.5 1 3 2 3-1 0-2 1.5-2 3v2c0 2-1 3-3 3"/>',
        alignLeft: '<path d="M4 3v18"/><rect x="8" y="6" width="12" height="4" rx="1"/><rect x="8" y="14" width="7" height="4" rx="1"/>',
        alignCenter: '<path d="M12 3v18"/><rect x="5" y="6" width="14" height="4" rx="1"/><rect x="8" y="14" width="8" height="4" rx="1"/>',
        alignRight: '<path d="M20 3v18"/><rect x="4" y="6" width="12" height="4" rx="1"/><rect x="9" y="14" width="7" height="4" rx="1"/>',
        alignTop: '<path d="M3 4h18"/><rect x="6" y="8" width="4" height="12" rx="1"/><rect x="14" y="8" width="4" height="7" rx="1"/>',
        alignMiddle: '<path d="M3 12h18"/><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="8" width="4" height="8" rx="1"/>',
        alignBottom: '<path d="M3 20h18"/><rect x="6" y="4" width="4" height="12" rx="1"/><rect x="14" y="9" width="4" height="7" rx="1"/>',
        distributeH: '<path d="M3 4v16"/><path d="M21 4v16"/><rect x="9" y="7" width="6" height="10" rx="1"/>',
        distributeV: '<path d="M4 3h16"/><path d="M4 21h16"/><rect x="7" y="9" width="10" height="6" rx="1"/>',
        zoomIn: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6"/><path d="M8 11h6"/>',
        zoomOut: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/><path d="M8 11h6"/>',
        fit: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
        eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
        eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2"/><path d="M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/>',
        lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
        unlock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
        up: '<path d="m6 15 6-6 6 6"/>',
        down: '<path d="m6 9 6 6 6-6"/>',
        trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>',
        copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M4 16V5a2 2 0 0 1 2-2h11"/>',
    };

    function icon(name) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
    }

    function fmt(text, values) {
        return String(text).replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    }

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function roundTo(value, digits) {
        const factor = 10 ** digits;
        return Math.round(value * factor) / factor;
    }

    function finite(value, fallback) {
        return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
    }

    function isObject(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    function isColor(value) {
        return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // --- state --------------------------------------------------------------

    const state = {
        // {template, filename, design, history, dirty, customFormat}
        entries: [],
        current: -1,
        boothLoadError: null,
        textValues: { event: I18N.sample_event, date: '13/09/2026', time: '21:47' },
        activeLevelId: null,
        selectedIds: [],
        clipboard: null,
        gridEnabled: false,
        gridSize: 30,
        busy: false,
    };

    let nextId = 1;
    const newId = prefix => `${prefix}${nextId++}`;

    function currentEntry() {
        return state.entries[state.current] || null;
    }

    function makeEntry(template, filename) {
        return { template: clone(template), filename, design: null, history: null, dirty: false, customFormat: false };
    }

    // --- the design model ---------------------------------------------------

    const COMMON_DEFAULTS = { x: 0, y: 0, width: 100, height: 100, angle: 0, opacity: 1, flipX: false, flipY: false };
    const KIND_DEFAULTS = {
        image: { src: '' },
        rect: { fill: '#d4a373', stroke: null, strokeWidth: 0, radius: 0 },
        ellipse: { fill: '#d4a373', stroke: null, strokeWidth: 0 },
        line: { stroke: '#232946', strokeWidth: 8 },
        label: { text: '', font: 'playfair', fontSize: 120, bold: false, italic: false, color: '#232946', align: 'center' },
        photo: { number: 1 },
        field: { text: '{event}', color: '#000000', align: 'center', bold: false },
    };

    function makeElement(kind, props) {
        return Object.assign({ id: newId('e'), kind }, clone(COMMON_DEFAULTS), clone(KIND_DEFAULTS[kind]), props || {});
    }

    function makeLevel(name, elements) {
        return { id: newId('l'), name, visible: true, locked: false, opacity: 1, elements: elements || [] };
    }

    // A design read from a file is data from outside: every field is checked
    // and given its type, and anything unknown is dropped.
    function normaliseElement(raw) {
        if (!isObject(raw) || !ELEMENT_KINDS.includes(raw.kind)) return null;
        const result = makeElement(raw.kind);
        for (const [key, fallback] of Object.entries(Object.assign({}, COMMON_DEFAULTS, KIND_DEFAULTS[raw.kind]))) {
            const value = raw[key];
            if (typeof fallback === 'number') result[key] = finite(value, fallback);
            else if (typeof fallback === 'boolean') result[key] = typeof value === 'boolean' ? value : fallback;
            else if (key === 'fill' || key === 'stroke' || key === 'color') result[key] = isColor(value) ? value : (value === null ? null : fallback);
            else result[key] = typeof value === 'string' ? value : fallback;
        }
        result.width = Math.max(1, result.width);
        result.height = Math.max(1, result.height);
        result.opacity = clamp(result.opacity, 0, 1);
        if (!['left', 'center', 'right'].includes(result.align)) result.align = 'center';
        return result;
    }

    function normaliseDesign(raw) {
        const levels = (Array.isArray(raw && raw.levels) ? raw.levels : []).filter(isObject).map(level => ({
            id: newId('l'),
            name: typeof level.name === 'string' && level.name.trim() ? level.name.slice(0, 60) : I18N.level_default_name,
            visible: level.visible !== false,
            locked: level.locked === true,
            opacity: clamp(finite(level.opacity, 1), 0, 1),
            elements: (Array.isArray(level.elements) ? level.elements : []).map(normaliseElement).filter(Boolean),
        }));
        if (!levels.length) levels.push(makeLevel(I18N.level_default_name));
        return { version: 1, levels };
    }

    function boxOf(raw) {
        return { x: raw.x, y: raw.y, width: raw.width, height: raw.height };
    }

    // A template made before designs existed, or written by hand: its layers
    // become levels, in the order the booth has always drawn them.
    function designFromTemplate(template) {
        const page = template.page;
        const fullPage = { x: 0, y: 0, width: page.width, height: page.height };
        const photos = (template.photos || []).map((photo, index) => makeElement('photo', Object.assign(boxOf(photo), { number: index + 1 })));
        const fields = (template.texts || []).map(text => makeElement('field', Object.assign(boxOf(text), {
            text: text.text || '', color: isColor(text.color) ? text.color : '#000000',
            align: text.align || 'center', bold: !!text.bold,
        })));
        const levels = [];

        if (Array.isArray(template.stack) && template.stack.length) {
            const elements = template.stack.map(entry => {
                const opacity = finite(entry.opacity, 1);
                if (entry.type === 'photo' && photos[entry.index]) return Object.assign(photos[entry.index], { opacity });
                if (entry.type === 'text' && fields[entry.index]) return Object.assign(fields[entry.index], { opacity });
                if (entry.type === 'image') return makeElement('image', Object.assign(boxOf(entry), { src: entry.src, opacity }));
                return null;
            }).filter(Boolean);
            levels.push(makeLevel(I18N.level_layout, elements));
        } else {
            if (template.background) {
                levels.push(makeLevel(I18N.level_background, [makeElement('image', Object.assign({ src: template.background }, fullPage))]));
            }
            levels.push(makeLevel(I18N.level_photos, photos));
            if (template.foreground) {
                levels.push(makeLevel(I18N.level_foreground, [makeElement('image', Object.assign({ src: template.foreground }, fullPage))]));
            }
            if (fields.length) {
                levels.push(makeLevel(I18N.level_texts, fields));
            }
        }
        return { version: 1, levels };
    }

    function openEntry(entry) {
        if (entry.design) return;
        entry.design = isObject(entry.template.design)
            ? normaliseDesign(entry.template.design)
            : designFromTemplate(entry.template);
        entry.customFormat = detectFormat(entry.template.page) === 'custom';
        entry.history = { states: [snapshot(entry)], index: 0 };
    }

    function allElements(design) {
        return design.levels.flatMap(level => level.elements);
    }

    function findElement(id) {
        const entry = currentEntry();
        if (!entry) return null;
        for (let levelIndex = 0; levelIndex < entry.design.levels.length; levelIndex++) {
            const level = entry.design.levels[levelIndex];
            const index = level.elements.findIndex(item => item.id === id);
            if (index >= 0) return { element: level.elements[index], level, index, levelIndex };
        }
        return null;
    }

    function selectedElements() {
        return state.selectedIds.map(findElement).filter(Boolean);
    }

    function activeLevel(entry) {
        const levels = entry.design.levels;
        return levels.find(level => level.id === state.activeLevelId) || levels[levels.length - 1];
    }

    function elementName(item) {
        const excerpt = text => {
            const flat = String(text || '').replace(/\s+/g, ' ').trim();
            return flat.length > 28 ? `${flat.slice(0, 27)}…` : flat;
        };
        switch (item.kind) {
            case 'photo': return fmt(I18N.canvas_photo, { number: item.number });
            case 'field': return fmt(I18N.element_field, { text: excerpt(item.text) });
            case 'label': return excerpt(item.text) || I18N.kind_label;
            default: return I18N[`kind_${item.kind}`];
        }
    }

    // Photo slots and variable texts are drawn by the booth itself, which
    // neither turns nor mirrors them, and refuses a box off the page.
    function clampSlot(item, page) {
        item.angle = 0;
        item.flipX = false;
        item.flipY = false;
        item.width = Math.round(clamp(item.width, MIN_BOX, page.width));
        item.height = Math.round(clamp(item.height, MIN_BOX, page.height));
        item.x = Math.round(clamp(item.x, 0, page.width - item.width));
        item.y = Math.round(clamp(item.y, 0, page.height - item.height));
    }

    function tidyGeometry(item, page) {
        if (SLOT_KINDS.includes(item.kind)) {
            clampSlot(item, page);
            return;
        }
        item.width = roundTo(Math.max(1, item.width), 1);
        item.height = roundTo(Math.max(1, item.height), 1);
        item.x = roundTo(item.x, 1);
        item.y = roundTo(item.y, 1);
        item.angle = roundTo(((item.angle % 360) + 360) % 360, 2);
    }

    function renumberPhotos(design) {
        allElements(design)
            .filter(item => item.kind === 'photo')
            .sort((a, b) => a.number - b.number)
            .forEach((item, index) => { item.number = index + 1; });
    }

    // --- history ------------------------------------------------------------

    function snapshot(entry) {
        return JSON.stringify({
            page: entry.template.page,
            duplicate_horizontal: !!entry.template.duplicate_horizontal,
            duplicate_vertical: !!entry.template.duplicate_vertical,
            customFormat: entry.customFormat,
            design: entry.design,
        });
    }

    function pushHistory(entry) {
        const history = entry.history;
        const current = snapshot(entry);
        if (history.states[history.index] === current) return false;
        history.states.splice(history.index + 1);
        history.states.push(current);
        if (history.states.length > HISTORY_LIMIT) history.states.shift();
        history.index = history.states.length - 1;
        return true;
    }

    function restoreHistory(entry, index) {
        const data = JSON.parse(entry.history.states[index]);
        entry.history.index = index;
        entry.template.page = data.page;
        entry.template.duplicate_horizontal = data.duplicate_horizontal;
        entry.template.duplicate_vertical = data.duplicate_vertical;
        entry.customFormat = data.customFormat;
        entry.design = data.design;
        entry.dirty = true;
        state.selectedIds = state.selectedIds.filter(id => findElement(id));
        renderAll();
    }

    function undo() {
        const entry = currentEntry();
        if (entry && entry.history.index > 0) restoreHistory(entry, entry.history.index - 1);
    }

    function redo() {
        const entry = currentEntry();
        if (entry && entry.history.index < entry.history.states.length - 1) restoreHistory(entry, entry.history.index + 1);
    }

    // After every change the operator means to keep: one undo step, and the
    // canvas, the levels and (unless an input is being typed in) the panel
    // drawn again from the design.
    function commit(options) {
        const entry = currentEntry();
        if (!entry) return;
        const page = entry.template.page;
        allElements(entry.design).forEach(item => tidyGeometry(item, page));
        if (pushHistory(entry) && !entry.dirty) {
            entry.dirty = true;
            renderTemplateList();
        }
        renderDesign();
        renderLevels();
        if (!options || options.panel !== false) renderProperties();
        updateToolbar();
    }

    // --- images, fonts and samples ------------------------------------------

    const images = new Map();

    function imageUrl(src) {
        if (typeof src !== 'string') return null;
        if (/^data:image\/(png|jpe?g|webp);base64,/i.test(src)) return src;
        const match = /^assets\/([0-9a-f]{32}\.(?:png|jpg|webp))$/.exec(src);
        return match ? `/api/template-assets/${match[1]}` : null;
    }

    function loadImage(src) {
        const url = imageUrl(src);
        if (!url) return Promise.resolve(null);
        let record = images.get(url);
        if (!record) {
            const image = new Image();
            record = { image, status: 'loading' };
            record.promise = new Promise(resolve => {
                image.onload = () => { record.status = 'ready'; resolve(image); };
                image.onerror = () => { record.status = 'failed'; resolve(null); };
            });
            image.src = url;
            images.set(url, record);
            record.promise.then(scheduleRender);
        }
        return record.promise;
    }

    function imageStatus(src) {
        const record = images.get(imageUrl(src));
        return record ? record.status : (imageUrl(src) ? 'loading' : 'failed');
    }

    function readyImage(src) {
        const record = images.get(imageUrl(src));
        return record && record.status === 'ready' ? record.image : null;
    }

    const samples = Array.from({ length: CONFIG.samplePhotoCount }, (_, number) => {
        const image = new Image();
        image.onload = scheduleRender;
        image.src = `/admin/editor/samples/${number}`;
        return image;
    });

    const FONTS = [{ id: 'print', label: I18N.font_print }].concat(CONFIG.fonts);

    function fontFamily(id) {
        return FONTS.some(font => font.id === id) && id !== 'print' ? `design-${id}` : 'PrintFont';
    }

    async function loadFonts(design) {
        const wanted = new Set(['16px PrintFont', 'bold 16px PrintFont']);
        allElements(design).filter(item => item.kind === 'label').forEach(item => {
            wanted.add(`${item.italic ? 'italic ' : ''}${item.bold ? 'bold ' : ''}40px ${fontFamily(item.font)}`);
        });
        await Promise.all([...wanted].map(font => document.fonts.load(font).catch(() => null)));
    }

    // --- drawing on the canvas ----------------------------------------------

    Object.assign(fabric.InteractiveFabricObject.ownDefaults, {
        borderColor: '#4a43b5',
        cornerColor: '#ffffff',
        cornerStrokeColor: '#4a43b5',
        cornerStyle: 'circle',
        cornerSize: 11,
        transparentCorners: false,
        borderScaleFactor: 1.5,
        lockScalingFlip: true,
    });

    function zoomOf(object) {
        return object.canvas ? object.canvas.getZoom() : 1;
    }

    function drawBadge(ctx, object, text, color) {
        const scale = 1 / zoomOf(object);
        ctx.save();
        ctx.font = `${12 * scale}px sans-serif`;
        const width = ctx.measureText(text).width + 12 * scale;
        const left = -object.width / 2 + 4 * scale;
        const top = -object.height / 2 + 4 * scale;
        ctx.globalAlpha = 1;
        ctx.fillStyle = color;
        ctx.fillRect(left, top, width, 18 * scale);
        ctx.fillStyle = '#ffffff';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, left + 6 * scale, top + 9 * scale);
        ctx.restore();
    }

    // The booth crops a photo to its slot the same way: centred, cover.
    function coverCrop(imageWidth, imageHeight, width, height) {
        if (imageWidth / imageHeight > width / height) {
            const cropWidth = Math.floor(width / (height / imageHeight));
            return { x: Math.floor((imageWidth - cropWidth) / 2), y: 0, width: cropWidth, height: imageHeight };
        }
        const cropHeight = Math.floor(height / (width / imageWidth));
        return { x: 0, y: Math.floor((imageHeight - cropHeight) / 2), width: imageWidth, height: cropHeight };
    }

    class PhotoSlot extends fabric.Rect {
        _render(ctx) {
            const width = this.width;
            const height = this.height;
            const sample = samples[(this.slotNumber - 1) % samples.length];
            if (sample && sample.complete && sample.naturalWidth) {
                const crop = coverCrop(sample.naturalWidth, sample.naturalHeight, width, height);
                ctx.drawImage(sample, crop.x, crop.y, crop.width, crop.height, -width / 2, -height / 2, width, height);
            } else {
                ctx.fillStyle = 'rgba(74, 67, 181, 0.25)';
                ctx.fillRect(-width / 2, -height / 2, width, height);
            }
            if (!this.plain) drawBadge(ctx, this, fmt(I18N.canvas_photo, { number: this.slotNumber }), 'rgba(74, 67, 181, 0.9)');
        }
    }

    function fillPlaceholders(text) {
        return String(text || '').replace(/\{(event|date|time)\}/g, (match, key) => state.textValues[key] || '');
    }

    function measureTextBlock(ctx, lines, size, bold) {
        ctx.font = `${bold ? 'bold ' : ''}${size}px PrintFont, sans-serif`;
        let width = 0;
        let ascent = size * 0.93;
        let descent = size * 0.24;
        lines.forEach(line => {
            const metrics = ctx.measureText(line);
            width = Math.max(width, metrics.width);
            if (metrics.fontBoundingBoxAscent !== undefined) {
                ascent = metrics.fontBoundingBoxAscent;
                descent = metrics.fontBoundingBoxDescent;
            }
        });
        const lineHeight = ascent + descent;
        const spacing = Math.floor(size * TEXT_LINE_SPACING);
        return { width, height: lineHeight * lines.length + spacing * (lines.length - 1), lineHeight, ascent, spacing };
    }

    // The same search the booth runs: the largest size the lines fit the box in.
    function fitTextSize(ctx, lines, width, height, bold) {
        let low = 1;
        let high = Math.max(1, Math.floor(height));
        while (low < high) {
            const size = Math.floor((low + high + 1) / 2);
            const block = measureTextBlock(ctx, lines, size, bold);
            if (block.width <= width && block.height <= height) low = size;
            else high = size - 1;
        }
        return low;
    }

    class FieldBox extends fabric.Rect {
        _render(ctx) {
            const width = this.width;
            const height = this.height;
            const scale = 1 / zoomOf(this);
            if (!this.plain) {
                ctx.save();
                ctx.setLineDash([8 * scale, 4 * scale]);
                ctx.lineWidth = 1.5 * scale;
                ctx.strokeStyle = '#2e7d5b';
                ctx.strokeRect(-width / 2, -height / 2, width, height);
                ctx.restore();
            }

            const content = fillPlaceholders(this.fieldText).trim();
            if (content) {
                const lines = content.split('\n').map(line => line.trim());
                const key = `${lines.join('\n')}|${width}|${height}|${this.fieldBold}`;
                if (this._fitKey !== key) {
                    this._fitKey = key;
                    this._fitSize = fitTextSize(ctx, lines, width, height, this.fieldBold);
                }
                const size = this._fitSize;
                const block = measureTextBlock(ctx, lines, size, this.fieldBold);
                ctx.fillStyle = this.fieldColor;
                ctx.textBaseline = 'alphabetic';
                let top = -height / 2 + Math.floor((height - block.height) / 2);
                lines.forEach(line => {
                    const lineWidth = ctx.measureText(line).width;
                    let left = -width / 2 + (width - lineWidth) / 2;
                    if (this.fieldAlign === 'left') left = -width / 2;
                    if (this.fieldAlign === 'right') left = width / 2 - lineWidth;
                    ctx.fillText(line, left, top + block.ascent);
                    top += block.lineHeight + block.spacing;
                });
            }
            if (!this.plain) drawBadge(ctx, this, I18N.badge_field, 'rgba(46, 125, 91, 0.9)');
        }
    }

    class MissingImage extends fabric.Rect {
        _render(ctx) {
            const width = this.width;
            const height = this.height;
            const scale = 1 / zoomOf(this);
            ctx.save();
            ctx.fillStyle = 'rgba(178, 58, 72, 0.08)';
            ctx.fillRect(-width / 2, -height / 2, width, height);
            ctx.setLineDash([10 * scale, 6 * scale]);
            ctx.lineWidth = 2 * scale;
            ctx.strokeStyle = '#b23a48';
            ctx.strokeRect(-width / 2, -height / 2, width, height);
            ctx.restore();
            drawBadge(ctx, this, this.loading ? I18N.image_loading : I18N.image_missing, 'rgba(178, 58, 72, 0.9)');
        }
    }

    // One element as a Fabric object, placed by its centre so rotation turns
    // it in place. `mode` is 'edit' on the canvas; 'export' and 'snapshot'
    // draw the page as printed, without what only the editor shows.
    function buildObject(item, levelOpacity, mode) {
        const plain = mode !== 'edit';
        const common = {
            left: item.x + item.width / 2,
            top: item.y + item.height / 2,
            originX: 'center',
            originY: 'center',
            angle: item.angle,
            flipX: item.flipX,
            flipY: item.flipY,
            opacity: item.opacity * levelOpacity,
        };
        let object;

        switch (item.kind) {
            case 'rect':
                object = new fabric.Rect(Object.assign(common, {
                    width: item.width, height: item.height, rx: item.radius, ry: item.radius,
                    fill: item.fill || 'rgba(0,0,0,0)', stroke: item.stroke || null,
                    strokeWidth: item.stroke ? item.strokeWidth : 0, strokeUniform: true,
                }));
                break;
            case 'ellipse':
                object = new fabric.Ellipse(Object.assign(common, {
                    rx: item.width / 2, ry: item.height / 2,
                    fill: item.fill || 'rgba(0,0,0,0)', stroke: item.stroke || null,
                    strokeWidth: item.stroke ? item.strokeWidth : 0, strokeUniform: true,
                }));
                break;
            case 'line':
                object = new fabric.Rect(Object.assign(common, { width: item.width, height: item.strokeWidth, fill: item.stroke }));
                break;
            case 'image': {
                const image = readyImage(item.src);
                if (image) {
                    object = new fabric.FabricImage(image, Object.assign(common, {
                        scaleX: item.width / image.naturalWidth, scaleY: item.height / image.naturalHeight,
                    }));
                } else {
                    if (plain) return null;
                    loadImage(item.src);
                    object = new MissingImage(Object.assign(common, { width: item.width, height: item.height, objectCaching: false }));
                    object.loading = imageStatus(item.src) === 'loading';
                }
                break;
            }
            case 'label':
                object = new fabric.Textbox(item.text, Object.assign(common, {
                    width: item.width, fontFamily: fontFamily(item.font), fontSize: item.fontSize,
                    fontWeight: item.bold ? 'bold' : 'normal', fontStyle: item.italic ? 'italic' : 'normal',
                    fill: item.color, textAlign: item.align, lineHeight: 1.1, splitByGrapheme: false,
                }));
                // A text box is as tall as its lines: keep the design in step,
                // so its top stays where the operator put it.
                item.height = object.height;
                object.set('top', item.y + object.height / 2);
                break;
            case 'photo':
                object = new PhotoSlot(Object.assign(common, { width: item.width, height: item.height, objectCaching: false }));
                object.slotNumber = item.number;
                break;
            case 'field':
                object = new FieldBox(Object.assign(common, { width: item.width, height: item.height, objectCaching: false }));
                object.fieldText = item.text;
                object.fieldColor = item.color;
                object.fieldAlign = item.align;
                object.fieldBold = item.bold;
                break;
            default:
                return null;
        }

        object.elementId = item.id;
        if (plain) {
            object.plain = true;
            // Drawn straight onto the page rather than through a cache canvas,
            // whose resampling leaves half-transparent edges on shapes that
            // end exactly on a pixel.
            object.objectCaching = false;
        }
        if (SLOT_KINDS.includes(item.kind)) {
            object.set({ lockRotation: true });
            object.setControlVisible('mtr', false);
        }
        if (item.kind === 'line') {
            ['mt', 'mb', 'tl', 'tr', 'bl', 'br'].forEach(control => object.setControlVisible(control, false));
        }
        return object;
    }

    const canvasArea = byId('canvasArea');
    const canvas = new fabric.Canvas('designCanvas', {
        width: canvasArea.clientWidth,
        height: canvasArea.clientHeight,
        renderOnAddRemove: false,
        preserveObjectStacking: true,
        stopContextMenu: true,
        fireMiddleClick: false,
        selectionColor: 'rgba(74, 67, 181, 0.08)',
        selectionBorderColor: '#4a43b5',
        selectionLineWidth: 1,
    });
    let suppressSelectionEvents = false;
    let guides = [];
    let renderScheduled = false;

    function scheduleRender() {
        if (renderScheduled) return;
        renderScheduled = true;
        requestAnimationFrame(() => {
            renderScheduled = false;
            renderDesign();
        });
    }

    function renderDesign() {
        const entry = currentEntry();
        suppressSelectionEvents = true;
        canvas.discardActiveObject();
        canvas.remove(...canvas.getObjects());
        byId('emptyCanvas').hidden = !!entry;

        if (entry) {
            entry.design.levels.forEach(level => {
                level.elements.forEach(item => {
                    const object = buildObject(item, level.opacity, 'edit');
                    if (!object) return;
                    object.visible = level.visible;
                    object.selectable = !level.locked;
                    object.evented = !level.locked && level.visible;
                    canvas.add(object);
                });
            });

            const selected = canvas.getObjects().filter(object =>
                state.selectedIds.includes(object.elementId) && object.selectable && object.visible);
            if (selected.length === 1) {
                canvas.setActiveObject(selected[0]);
            } else if (selected.length > 1) {
                canvas.setActiveObject(new fabric.ActiveSelection(selected, { canvas }));
            }
            state.selectedIds = selected.map(object => object.elementId);
        }
        suppressSelectionEvents = false;
        canvas.requestRenderAll();
    }

    canvas.on('before:render', ({ ctx }) => {
        const entry = currentEntry();
        if (!entry) return;
        const v = canvas.viewportTransform;
        ctx.save();
        ctx.transform(v[0], v[1], v[2], v[3], v[4], v[5]);
        ctx.shadowColor = 'rgba(29, 32, 51, 0.18)';
        ctx.shadowBlur = 18;
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, entry.template.page.width, entry.template.page.height);
        ctx.restore();
    });

    canvas.on('after:render', ({ ctx }) => {
        const entry = currentEntry();
        // Fired for the selection layer as well, which must stay clear.
        if (!entry || ctx !== canvas.getContext()) return;
        const v = canvas.viewportTransform;
        const zoom = canvas.getZoom();
        const { width, height } = entry.template.page;
        ctx.save();
        ctx.transform(v[0], v[1], v[2], v[3], v[4], v[5]);

        // What lies off the page is cut on the print: shown veiled.
        ctx.beginPath();
        ctx.rect(-1e6, -1e6, 2e6, 2e6);
        ctx.rect(0, 0, width, height);
        ctx.fillStyle = 'rgba(226, 221, 213, 0.78)';
        ctx.fill('evenodd');

        if (state.gridEnabled && state.gridSize * zoom >= 6) {
            ctx.beginPath();
            for (let x = state.gridSize; x < width; x += state.gridSize) {
                ctx.moveTo(x, 0);
                ctx.lineTo(x, height);
            }
            for (let y = state.gridSize; y < height; y += state.gridSize) {
                ctx.moveTo(0, y);
                ctx.lineTo(width, y);
            }
            ctx.lineWidth = 1 / zoom;
            ctx.strokeStyle = 'rgba(74, 67, 181, 0.14)';
            ctx.stroke();
        }

        ctx.lineWidth = 1 / zoom;
        ctx.strokeStyle = 'rgba(29, 32, 51, 0.3)';
        ctx.strokeRect(0, 0, width, height);

        if (entry.template.duplicate_horizontal || entry.template.duplicate_vertical) {
            ctx.setLineDash([12 / zoom, 8 / zoom]);
            ctx.strokeStyle = 'rgba(29, 32, 51, 0.35)';
            const dx = entry.template.duplicate_horizontal ? width : 0;
            const dy = entry.template.duplicate_vertical ? height : 0;
            ctx.strokeRect(dx, dy, width, height);
            ctx.setLineDash([]);
            ctx.font = `${13 / zoom}px sans-serif`;
            ctx.fillStyle = 'rgba(29, 32, 51, 0.55)';
            ctx.textAlign = 'center';
            ctx.fillText(I18N.printed_twice, dx + width / 2, dy + height / 2);
        }

        if (guides.length) {
            ctx.beginPath();
            guides.forEach(guide => {
                if (guide.axis === 'x') {
                    ctx.moveTo(guide.value, -1e5);
                    ctx.lineTo(guide.value, 1e5);
                } else {
                    ctx.moveTo(-1e5, guide.value);
                    ctx.lineTo(1e5, guide.value);
                }
            });
            ctx.lineWidth = 1 / zoom;
            ctx.strokeStyle = '#d6336c';
            ctx.stroke();
        }
        ctx.restore();
    });

    // --- reading the pointer back into the design ---------------------------

    function readBackGeometry(object) {
        const found = findElement(object.elementId);
        if (!found) return;
        const item = found.element;
        const scaling = object.getObjectScaling();
        const scaleX = Math.abs(scaling.x);
        const scaleY = Math.abs(scaling.y);
        const center = object.getCenterPoint();
        let width;
        let height;

        switch (item.kind) {
            case 'ellipse':
                width = object.rx * 2 * scaleX;
                height = object.ry * 2 * scaleY;
                break;
            case 'line':
                width = object.width * scaleX;
                height = Math.max(1, object.height * scaleY);
                item.strokeWidth = roundTo(height, 1);
                break;
            case 'label':
                // Pulling a corner scales the lettering; pulling a side only
                // re-flows the lines in a wider or narrower box.
                if (Math.abs(scaleX - scaleY) < 0.001 && Math.abs(scaleX - 1) > 0.001) {
                    item.fontSize = roundTo(object.fontSize * scaleY, 1);
                }
                item.text = object.text;
                width = object.width * scaleX;
                height = object.height * scaleY;
                break;
            default:
                width = object.width * scaleX;
                height = object.height * scaleY;
        }

        item.width = width;
        item.height = height;
        item.x = center.x - width / 2;
        item.y = center.y - height / 2;
        item.angle = object.getTotalAngle();
        item.flipX = !!object.flipX;
        item.flipY = !!object.flipY;
    }

    // Fabric is still finishing the gesture when it reports it: drawing the
    // canvas again from inside would end the same transform a second time,
    // and report it again. The design is read now, the canvas rebuilt after.
    function commitAfterGesture() {
        setTimeout(commit, 0);
    }

    canvas.on('object:modified', event => {
        const target = event.target;
        if (!target) return;
        const objects = target instanceof fabric.ActiveSelection ? target.getObjects() : [target];
        objects.forEach(readBackGeometry);
        guides = [];
        commitAfterGesture();
    });

    canvas.on('text:editing:exited', event => {
        const found = event.target && findElement(event.target.elementId);
        if (found && found.element.text !== event.target.text) {
            found.element.text = event.target.text;
            commitAfterGesture();
        }
    });

    function syncSelectionFromCanvas() {
        if (suppressSelectionEvents) return;
        state.selectedIds = canvas.getActiveObjects().map(object => object.elementId).filter(Boolean);
        if (state.selectedIds.length) {
            const found = findElement(state.selectedIds[state.selectedIds.length - 1]);
            if (found) state.activeLevelId = found.level.id;
        }
        renderLevels();
        renderProperties();
        updateToolbar();
    }

    canvas.on('selection:created', syncSelectionFromCanvas);
    canvas.on('selection:updated', syncSelectionFromCanvas);
    canvas.on('selection:cleared', syncSelectionFromCanvas);

    // Snapping: edges and centres of the page and of the other elements pull
    // what is dragged, and a guide shows what it lined up with.
    function nearest(candidates, targets, threshold) {
        let best = null;
        candidates.forEach(candidate => targets.forEach(target => {
            const distance = Math.abs(target - candidate);
            if (distance <= threshold && (!best || distance < Math.abs(best.delta))) {
                best = { delta: target - candidate, value: target };
            }
        }));
        return best;
    }

    canvas.on('object:moving', event => {
        const entry = currentEntry();
        const target = event.target;
        if (!entry || !target) return;
        const page = entry.template.page;
        const moving = target instanceof fabric.ActiveSelection ? target.getObjects() : [target];
        const box = target.getBoundingRect();
        const threshold = SNAP_DISTANCE / canvas.getZoom();
        const others = canvas.getObjects().filter(object => object.visible && !moving.includes(object)).map(object => object.getBoundingRect());
        const xs = [0, page.width / 2, page.width].concat(others.flatMap(b => [b.left, b.left + b.width / 2, b.left + b.width]));
        const ys = [0, page.height / 2, page.height].concat(others.flatMap(b => [b.top, b.top + b.height / 2, b.top + b.height]));
        guides = [];

        const snapX = nearest([box.left, box.left + box.width / 2, box.left + box.width], xs, threshold);
        if (snapX) {
            target.set('left', target.left + snapX.delta);
            guides.push({ axis: 'x', value: snapX.value });
        } else if (state.gridEnabled) {
            target.set('left', target.left + Math.round(box.left / state.gridSize) * state.gridSize - box.left);
        }

        const snapY = nearest([box.top, box.top + box.height / 2, box.top + box.height], ys, threshold);
        if (snapY) {
            target.set('top', target.top + snapY.delta);
            guides.push({ axis: 'y', value: snapY.value });
        } else if (state.gridEnabled) {
            target.set('top', target.top + Math.round(box.top / state.gridSize) * state.gridSize - box.top);
        }
        target.setCoords();
    });

    canvas.on('mouse:up', () => {
        if (guides.length) {
            guides = [];
            canvas.requestRenderAll();
        }
    });

    // --- the view: zoom and pan ---------------------------------------------

    function updateZoomLabel() {
        byId('zoomLabel').textContent = `${Math.round(canvas.getZoom() * 100)}%`;
    }

    function fitView() {
        const entry = currentEntry();
        if (!entry) return;
        const { width, height } = entry.template.page;
        const areaWidth = canvas.getWidth();
        const areaHeight = canvas.getHeight();
        const padding = 48;
        const zoom = clamp(Math.min((areaWidth - padding * 2) / width, (areaHeight - padding * 2) / height), 0.02, 8);
        canvas.setViewportTransform([zoom, 0, 0, zoom, (areaWidth - width * zoom) / 2, (areaHeight - height * zoom) / 2]);
        updateZoomLabel();
    }

    function zoomAt(factor, point) {
        const zoom = clamp(canvas.getZoom() * factor, 0.02, 8);
        canvas.zoomToPoint(new fabric.Point(point.x, point.y), zoom);
        updateZoomLabel();
    }

    function zoomAtCentre(factor) {
        zoomAt(factor, { x: canvas.getWidth() / 2, y: canvas.getHeight() / 2 });
    }

    canvas.on('mouse:wheel', ({ e }) => {
        if (e.ctrlKey || e.metaKey) {
            zoomAt(Math.pow(0.998, e.deltaY), { x: e.offsetX, y: e.offsetY });
        } else {
            const v = canvas.viewportTransform.slice();
            v[4] -= e.shiftKey ? e.deltaY : e.deltaX;
            v[5] -= e.shiftKey ? 0 : e.deltaY;
            canvas.setViewportTransform(v);
        }
        e.preventDefault();
        e.stopPropagation();
    });

    let panning = null;
    let spaceHeld = false;

    canvasArea.addEventListener('pointerdown', event => {
        if (event.button === 1 || (event.button === 0 && spaceHeld)) {
            panning = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
            canvasArea.setPointerCapture(event.pointerId);
            canvasArea.classList.add('panning');
            event.preventDefault();
            event.stopPropagation();
        }
    }, true);

    canvasArea.addEventListener('pointermove', event => {
        if (!panning) return;
        const v = canvas.viewportTransform.slice();
        v[4] += event.clientX - panning.x;
        v[5] += event.clientY - panning.y;
        panning.x = event.clientX;
        panning.y = event.clientY;
        canvas.setViewportTransform(v);
        event.stopPropagation();
    }, true);

    function endPan(event) {
        if (!panning) return;
        canvasArea.releasePointerCapture(panning.pointerId);
        panning = null;
        canvasArea.classList.remove('panning');
        event.stopPropagation();
    }

    canvasArea.addEventListener('pointerup', endPan, true);
    canvasArea.addEventListener('pointercancel', endPan, true);

    let firstLayout = true;
    new ResizeObserver(() => {
        canvas.setDimensions({ width: canvasArea.clientWidth, height: canvasArea.clientHeight });
        if (firstLayout && currentEntry()) {
            firstLayout = false;
            fitView();
        }
        canvas.requestRenderAll();
    }).observe(canvasArea);

    // --- adding elements ----------------------------------------------------

    function targetLevel(entry) {
        let level = activeLevel(entry);
        if (!level || level.locked) {
            level = [...entry.design.levels].reverse().find(candidate => !candidate.locked);
        }
        if (!level) {
            level = makeLevel(fmt(I18N.level_numbered, { number: entry.design.levels.length + 1 }));
            entry.design.levels.push(level);
        }
        if (!level.visible) level.visible = true;
        state.activeLevelId = level.id;
        return level;
    }

    function addElement(kind, props) {
        const entry = currentEntry();
        if (!entry) return null;
        const page = entry.template.page;
        const centred = (width, height) => ({ x: (page.width - width) / 2, y: (page.height - height) / 2, width, height });
        let defaults;

        switch (kind) {
            case 'rect':
            case 'ellipse':
                defaults = centred(Math.round(page.width * 0.4), Math.round(page.height * 0.3));
                break;
            case 'line': {
                const strokeWidth = Math.max(2, Math.round(Math.min(page.width, page.height) / 150));
                defaults = Object.assign(centred(Math.round(page.width * 0.5), strokeWidth), { strokeWidth });
                break;
            }
            case 'label': {
                const width = Math.round(page.width * 0.6);
                defaults = Object.assign(centred(width, 100), {
                    text: I18N.new_label_text, fontSize: Math.round(Math.min(page.width, page.height) * 0.08),
                });
                break;
            }
            case 'photo': {
                const number = allElements(entry.design).filter(item => item.kind === 'photo').length + 1;
                const width = Math.round(Math.min(page.width * 0.5, page.height * 0.5 * 1.5));
                defaults = Object.assign(centred(width, Math.round(width / 1.5)), { number });
                break;
            }
            case 'field':
                defaults = centred(Math.round(page.width * 0.6), Math.round(page.height * 0.08));
                break;
            default:
                defaults = {};
        }

        const item = makeElement(kind, Object.assign(defaults, props || {}));
        targetLevel(entry).elements.push(item);
        state.selectedIds = [item.id];
        commit();
        return item;
    }

    async function uploadImageBlob(blob, name) {
        if (blob.size > CONFIG.assetBytesLimit) {
            throw new Error(fmt(I18N.image_too_heavy, { limit: Math.floor(CONFIG.assetBytesLimit / 1048576) }));
        }
        const form = new FormData();
        form.append('image', blob, name || 'image.png');
        const response = await fetch('/api/template-assets', { method: 'POST', body: form });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        return payload;
    }

    async function addImageFiles(files) {
        const entry = currentEntry();
        if (!entry) return;
        const page = entry.template.page;
        const accepted = [...files].filter(file => /^image\/(png|jpeg|webp)$/.test(file.type));
        if (!accepted.length) {
            if (files.length) alert(I18N.image_unsupported);
            return;
        }
        setBusy(I18N.uploading_image);
        try {
            for (const file of accepted) {
                const asset = await uploadImageBlob(file, file.name);
                await loadImage(asset.filename);
                const scale = Math.min(1, (page.width * 0.8) / asset.width, (page.height * 0.8) / asset.height);
                const width = Math.round(asset.width * scale);
                const height = Math.round(asset.height * scale);
                addElement('image', {
                    src: asset.filename, width, height,
                    x: Math.round((page.width - width) / 2), y: Math.round((page.height - height) / 2),
                });
            }
        } catch (error) {
            alert(fmt(I18N.image_failed, { error: error.message }));
        } finally {
            setBusy(null);
        }
    }

    async function replaceImage(id, file) {
        const found = findElement(id);
        if (!found || !file) return;
        setBusy(I18N.uploading_image);
        try {
            const asset = await uploadImageBlob(file, file.name);
            await loadImage(asset.filename);
            const item = found.element;
            // Same place, same width, the new picture's own proportions.
            const height = item.width * asset.height / asset.width;
            item.y += (item.height - height) / 2;
            item.height = height;
            item.src = asset.filename;
            commit();
        } catch (error) {
            alert(fmt(I18N.image_failed, { error: error.message }));
        } finally {
            setBusy(null);
        }
    }

    // --- editing the selection ----------------------------------------------

    function deleteSelection() {
        const entry = currentEntry();
        const found = selectedElements().filter(item => !item.level.locked);
        if (!entry || !found.length) return;
        found.forEach(({ element: item, level }) => {
            level.elements.splice(level.elements.indexOf(item), 1);
        });
        renumberPhotos(entry.design);
        state.selectedIds = [];
        commit();
    }

    function copySelection() {
        const found = selectedElements();
        if (found.length) state.clipboard = found.map(item => clone(item.element));
    }

    function pasteElements(items, offset) {
        const entry = currentEntry();
        if (!entry || !items || !items.length) return;
        const level = targetLevel(entry);
        let photoCount = allElements(entry.design).filter(item => item.kind === 'photo').length;
        state.selectedIds = items.map(source => {
            const item = Object.assign(clone(source), { id: newId('e'), x: source.x + offset, y: source.y + offset });
            if (item.kind === 'photo') item.number = ++photoCount;
            level.elements.push(item);
            return item.id;
        });
        commit();
    }

    function duplicateSelection() {
        const found = selectedElements();
        if (found.length) pasteElements(found.map(item => item.element), 30);
    }

    function nudgeSelection(dx, dy) {
        const found = selectedElements().filter(item => !item.level.locked);
        if (!found.length) return;
        found.forEach(({ element: item }) => {
            item.x += dx;
            item.y += dy;
        });
        commit();
    }

    function moveElement(id, direction) {
        const entry = currentEntry();
        const found = findElement(id);
        if (!entry || !found) return;
        const { element: item, level, index, levelIndex } = found;
        const target = index + direction;
        level.elements.splice(index, 1);
        if (target >= 0 && target <= level.elements.length) {
            level.elements.splice(target, 0, item);
        } else {
            // Past the end of its level: into the next one up or down.
            const next = entry.design.levels[levelIndex + direction];
            if (!next) {
                level.elements.splice(index, 0, item);
                return;
            }
            if (direction > 0) next.elements.unshift(item);
            else next.elements.push(item);
            state.activeLevelId = next.id;
        }
        commit();
    }

    function align(mode) {
        const entry = currentEntry();
        const objects = canvas.getActiveObjects();
        if (!entry || !objects.length) return;
        const boxes = objects.map(object => ({ object, box: object.getBoundingRect() }));
        let reference = { left: 0, top: 0, width: entry.template.page.width, height: entry.template.page.height };
        if (objects.length > 1) {
            const left = Math.min(...boxes.map(b => b.box.left));
            const top = Math.min(...boxes.map(b => b.box.top));
            const right = Math.max(...boxes.map(b => b.box.left + b.box.width));
            const bottom = Math.max(...boxes.map(b => b.box.top + b.box.height));
            reference = { left, top, width: right - left, height: bottom - top };
        }
        boxes.forEach(({ object, box }) => {
            const found = findElement(object.elementId);
            if (!found) return;
            const item = found.element;
            if (mode === 'left') item.x += reference.left - box.left;
            if (mode === 'center') item.x += reference.left + reference.width / 2 - (box.left + box.width / 2);
            if (mode === 'right') item.x += reference.left + reference.width - (box.left + box.width);
            if (mode === 'top') item.y += reference.top - box.top;
            if (mode === 'middle') item.y += reference.top + reference.height / 2 - (box.top + box.height / 2);
            if (mode === 'bottom') item.y += reference.top + reference.height - (box.top + box.height);
        });
        commit();
    }

    function distribute(direction) {
        const objects = canvas.getActiveObjects();
        if (objects.length < 3) return;
        const horizontal = direction === 'horizontal';
        const items = objects.map(object => {
            const box = object.getBoundingRect();
            return { found: findElement(object.elementId), centre: horizontal ? box.left + box.width / 2 : box.top + box.height / 2 };
        }).filter(item => item.found).sort((a, b) => a.centre - b.centre);
        const first = items[0].centre;
        const step = (items[items.length - 1].centre - first) / (items.length - 1);
        items.forEach((item, index) => {
            const delta = first + step * index - item.centre;
            if (horizontal) item.found.element.x += delta;
            else item.found.element.y += delta;
        });
        commit();
    }

    // --- levels -------------------------------------------------------------

    function addLevel() {
        const entry = currentEntry();
        if (!entry) return;
        const levels = entry.design.levels;
        const level = makeLevel(fmt(I18N.level_numbered, { number: levels.length + 1 }));
        const active = levels.indexOf(activeLevel(entry));
        levels.splice(active + 1, 0, level);
        state.activeLevelId = level.id;
        commit();
    }

    function deleteLevel(id) {
        const entry = currentEntry();
        const levels = entry.design.levels;
        const index = levels.findIndex(level => level.id === id);
        if (index < 0) return;
        if (levels.length === 1) {
            alert(I18N.keep_one_level);
            return;
        }
        const level = levels[index];
        if (level.elements.length && !confirm(fmt(I18N.confirm_delete_level, { name: level.name, count: level.elements.length }))) {
            return;
        }
        levels.splice(index, 1);
        renumberPhotos(entry.design);
        state.selectedIds = state.selectedIds.filter(selected => findElement(selected));
        state.activeLevelId = levels[Math.max(0, index - 1)].id;
        commit();
    }

    function moveLevel(id, direction) {
        const levels = currentEntry().design.levels;
        const index = levels.findIndex(level => level.id === id);
        const target = index + direction;
        if (index < 0 || target < 0 || target >= levels.length) return;
        levels.splice(target, 0, levels.splice(index, 1)[0]);
        commit();
    }

    function rowButton(iconName, title, onClick, options) {
        const button = element('button', `row-button${options && options.className ? ` ${options.className}` : ''}`);
        button.type = 'button';
        button.title = title;
        button.setAttribute('aria-label', title);
        button.innerHTML = icon(iconName);
        button.disabled = !!(options && options.disabled);
        button.addEventListener('click', event => {
            event.stopPropagation();
            onClick();
        });
        return button;
    }

    function renderLevels() {
        const list = byId('levelList');
        list.replaceChildren();
        const entry = currentEntry();
        byId('addLevelButton').disabled = !entry;
        if (!entry) return;

        const levels = entry.design.levels;
        const active = activeLevel(entry);
        // Top of the list is top of the page, as in any drawing program.
        [...levels].reverse().forEach(level => {
            const levelIndex = levels.indexOf(level);
            const box = element('div', `level${level === active ? ' active' : ''}${level.visible ? '' : ' hidden-level'}`);
            const head = element('div', 'level-head');
            // Choosing a level puts its own settings in the panel, and is
            // where the next element will go.
            head.addEventListener('click', () => {
                state.activeLevelId = level.id;
                state.selectedIds = [];
                renderDesign();
                renderLevels();
                renderProperties();
                updateToolbar();
            });
            head.append(
                rowButton(level.visible ? 'eye' : 'eyeOff', level.visible ? I18N.hide_level : I18N.show_level, () => {
                    level.visible = !level.visible;
                    commit();
                }, { className: level.visible ? '' : 'off' }),
                rowButton(level.locked ? 'lock' : 'unlock', level.locked ? I18N.unlock_level : I18N.lock_level, () => {
                    level.locked = !level.locked;
                    if (level.locked) state.selectedIds = state.selectedIds.filter(id => !level.elements.some(item => item.id === id));
                    commit();
                }, { className: level.locked ? 'on' : 'off' }),
                element('span', 'level-name', level.name),
            );
            if (level.opacity < 1) head.append(element('span', 'level-opacity', `${Math.round(level.opacity * 100)}%`));
            head.append(
                rowButton('up', I18N.level_up, () => moveLevel(level.id, 1), { disabled: levelIndex === levels.length - 1 }),
                rowButton('down', I18N.level_down, () => moveLevel(level.id, -1), { disabled: levelIndex === 0 }),
                rowButton('trash', I18N.delete_level, () => deleteLevel(level.id)),
            );
            box.append(head);

            if (!level.elements.length) {
                box.append(element('div', 'level-empty', I18N.level_empty));
            }
            [...level.elements].reverse().forEach(item => {
                const row = element('div', `element-row${state.selectedIds.includes(item.id) ? ' selected' : ''}`);
                const kindIcon = element('span', 'element-icon');
                kindIcon.innerHTML = icon(item.kind === 'label' ? 'label' : item.kind);
                row.append(kindIcon, element('span', 'element-name', elementName(item)));
                if (SLOT_KINDS.includes(item.kind) || item.opacity < 1) {
                    row.title = item.opacity < 1 ? `${Math.round(item.opacity * 100)}%` : '';
                }
                const index = level.elements.indexOf(item);
                row.append(
                    rowButton('up', I18N.element_up, () => moveElement(item.id, 1), {
                        disabled: index === level.elements.length - 1 && levelIndex === levels.length - 1,
                    }),
                    rowButton('down', I18N.element_down, () => moveElement(item.id, -1), {
                        disabled: index === 0 && levelIndex === 0,
                    }),
                );
                row.addEventListener('click', event => {
                    if (level.locked || !level.visible) {
                        state.activeLevelId = level.id;
                        renderLevels();
                        return;
                    }
                    if (event.shiftKey || event.ctrlKey || event.metaKey) {
                        state.selectedIds = state.selectedIds.includes(item.id)
                            ? state.selectedIds.filter(id => id !== item.id)
                            : state.selectedIds.concat(item.id);
                    } else {
                        state.selectedIds = [item.id];
                    }
                    state.activeLevelId = level.id;
                    renderDesign();
                    renderLevels();
                    renderProperties();
                    updateToolbar();
                });
                box.append(row);
            });
            list.append(box);
        });
    }

    // --- the properties panel -----------------------------------------------

    function section(parent, title) {
        const node = element('div', 'prop-section');
        if (title) node.append(element('h3', null, title));
        parent.append(node);
        return node;
    }

    function row(parent, label, control) {
        const node = element('label', 'prop-row');
        node.append(element('span', null, label), control);
        parent.append(node);
        return control;
    }

    function numberInput(value, onChange, options) {
        const input = document.createElement('input');
        input.type = 'number';
        input.value = roundTo(value, 1);
        input.step = (options && options.step) || 1;
        if (options && options.min !== undefined) input.min = options.min;
        if (options && options.max !== undefined) input.max = options.max;
        input.addEventListener('change', () => {
            const number = Number(input.value);
            if (input.value !== '' && Number.isFinite(number)) onChange(number);
        });
        commitOnEnter(input);
        return input;
    }

    // Enter settles a number or a line of text the way leaving the field
    // does; a browser does not always send `change` for it.
    function commitOnEnter(input) {
        input.addEventListener('keydown', event => {
            if (event.key === 'Enter') input.blur();
        });
    }

    function textInput(value, onInput, onChange, multiline) {
        const input = document.createElement(multiline ? 'textarea' : 'input');
        if (!multiline) {
            input.type = 'text';
            commitOnEnter(input);
        }
        input.value = value;
        input.addEventListener('input', () => onInput(input.value));
        input.addEventListener('change', () => onChange(input.value));
        return input;
    }

    function colorInput(value, onInput, onChange) {
        const input = document.createElement('input');
        input.type = 'color';
        input.value = isColor(value) ? value : '#000000';
        input.addEventListener('input', () => onInput(input.value));
        input.addEventListener('change', () => onChange(input.value));
        return input;
    }

    function selectInput(options, value, onChange) {
        const select = document.createElement('select');
        options.forEach(option => {
            const node = element('option', null, option.label);
            node.value = option.value;
            select.append(node);
        });
        select.value = String(value);
        select.addEventListener('change', () => onChange(select.value));
        return select;
    }

    function opacityInput(value, onInput, onChange) {
        const wrapper = element('div', 'prop-inline');
        const input = document.createElement('input');
        input.type = 'range';
        input.min = 0;
        input.max = 100;
        input.value = Math.round(value * 100);
        const output = element('output', null, `${input.value}%`);
        input.addEventListener('input', () => {
            output.textContent = `${input.value}%`;
            onInput(Number(input.value) / 100);
        });
        input.addEventListener('change', () => onChange(Number(input.value) / 100));
        wrapper.append(input, output);
        return wrapper;
    }

    function checkbox(parent, label, checked, onChange) {
        const node = element('label', 'prop-check');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = checked;
        input.addEventListener('change', () => onChange(input.checked));
        node.append(input, document.createTextNode(label));
        parent.append(node);
        return input;
    }

    function buttons(parent, specs) {
        const node = element('div', 'prop-buttons');
        specs.forEach(spec => {
            const button = element('button', `btn ${spec.className || 'btn-secondary'}`, spec.label);
            button.type = 'button';
            button.addEventListener('click', spec.onClick);
            node.append(button);
        });
        parent.append(node);
        return node;
    }

    // Live changes redraw the canvas only; the change that ends an edit is
    // one undo step. The panel is left alone so the field keeps its focus.
    function liveEdit(item, changes) {
        Object.assign(item, changes);
        renderDesign();
        renderLevels();
    }

    function finalEdit(item, changes) {
        Object.assign(item, changes);
        commit({ panel: false });
    }

    function renderProperties() {
        const panel = byId('properties');
        panel.replaceChildren();
        const entry = currentEntry();
        if (!entry) return;

        const found = selectedElements();
        if (found.length === 1) {
            renderElementProperties(panel, entry, found[0]);
        } else if (found.length > 1) {
            renderMultipleProperties(panel, found);
        } else {
            renderTemplateProperties(panel, entry);
        }
    }

    function renderTemplateProperties(panel, entry) {
        const template = section(panel, I18N.template_properties);
        row(template, I18N.name, textInput(entry.template.name || '', value => {
            entry.template.name = value;
            markDirty(entry);
            renderTemplateList();
        }, () => {}));
        row(template, I18N.description, textInput(entry.template.description || '', value => {
            entry.template.description = value;
            markDirty(entry);
            renderTemplateList();
        }, () => {}));

        const level = activeLevel(entry);
        const levelSection = section(panel, I18N.active_level);
        row(levelSection, I18N.name, textInput(level.name, value => {
            level.name = value.slice(0, 60);
            renderLevels();
        }, value => {
            level.name = value.trim().slice(0, 60) || I18N.level_default_name;
            commit({ panel: false });
        }));
        row(levelSection, I18N.opacity, opacityInput(level.opacity, value => {
            level.opacity = value;
            renderDesign();
            renderLevels();
        }, value => {
            level.opacity = value;
            commit({ panel: false });
        }));

        const help = section(panel, I18N.shortcuts);
        const list = element('ul', 'shortcut-list info-text');
        [I18N.shortcut_add, I18N.shortcut_select, I18N.shortcut_zoom, I18N.shortcut_pan, I18N.shortcut_undo,
            I18N.shortcut_copy, I18N.shortcut_arrows, I18N.shortcut_delete, I18N.shortcut_levels]
            .forEach(text => list.append(element('li', null, text)));
        help.append(list);
    }

    function renderMultipleProperties(panel, found) {
        const node = section(panel, fmt(I18N.selection_count, { count: found.length }));
        const average = found.reduce((sum, item) => sum + item.element.opacity, 0) / found.length;
        row(node, I18N.opacity, opacityInput(average, value => {
            found.forEach(item => { item.element.opacity = value; });
            renderDesign();
        }, value => {
            found.forEach(item => { item.element.opacity = value; });
            commit({ panel: false });
        }));
        buttons(node, [
            { label: I18N.duplicate, onClick: duplicateSelection },
            { label: I18N.delete, className: 'btn-danger', onClick: deleteSelection },
        ]);
    }

    function renderElementProperties(panel, entry, found) {
        const item = found.element;
        const page = entry.template.page;
        const locked = found.level.locked;
        const isSlot = SLOT_KINDS.includes(item.kind);

        // The kind, not the text: the heading is not redrawn while typing.
        const heading = item.kind === 'photo' ? elementName(item)
            : item.kind === 'field' ? I18N.badge_field : I18N[`kind_${item.kind}`];
        const geometry = section(panel, heading);
        const grid = element('div', 'prop-grid');
        geometry.append(grid);
        const geometryInput = (label, key, options) => row(grid, label, numberInput(item[key], value => finalEdit(item, { [key]: value }), options));
        geometryInput(I18N.x, 'x');
        geometryInput(I18N.y, 'y');
        geometryInput(I18N.width, 'width', { min: 1 });
        if (item.kind === 'line') {
            row(grid, I18N.thickness, numberInput(item.strokeWidth, value => finalEdit(item, { strokeWidth: Math.max(1, value), height: Math.max(1, value) }), { min: 1 }));
        } else if (item.kind !== 'label') {
            geometryInput(I18N.height, 'height', { min: 1 });
        }
        if (!isSlot) {
            geometryInput(I18N.rotation, 'angle', { step: 1 });
        }
        row(geometry, I18N.opacity, opacityInput(item.opacity, value => liveEdit(item, { opacity: value }), value => finalEdit(item, { opacity: value })));

        const look = section(panel, I18N.appearance);
        switch (item.kind) {
            case 'image':
                checkbox(look, I18N.flip_horizontal, item.flipX, value => finalEdit(item, { flipX: value }));
                checkbox(look, I18N.flip_vertical, item.flipY, value => finalEdit(item, { flipY: value }));
                if (imageStatus(item.src) === 'failed') look.append(element('div', 'info-text', I18N.image_missing_help));
                {
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.accept = 'image/png,image/jpeg,image/webp';
                    input.hidden = true;
                    input.addEventListener('change', () => replaceImage(item.id, input.files[0]));
                    look.append(input);
                    buttons(look, [
                        { label: I18N.replace_image, onClick: () => input.click() },
                        { label: I18N.fit_page, onClick: () => finalEdit(item, fitToPage(item, page)) },
                    ]);
                }
                break;
            case 'rect':
            case 'ellipse':
                checkbox(look, I18N.fill, !!item.fill, value => finalEdit(item, { fill: value ? (item.lastFill || '#d4a373') : null, lastFill: item.fill || item.lastFill }));
                if (item.fill) {
                    row(look, I18N.fill_color, colorInput(item.fill, value => liveEdit(item, { fill: value }), value => finalEdit(item, { fill: value })));
                }
                checkbox(look, I18N.outline, !!item.stroke, value => finalEdit(item, {
                    stroke: value ? '#232946' : null,
                    strokeWidth: value ? Math.max(item.strokeWidth, Math.round(Math.min(page.width, page.height) / 200)) : item.strokeWidth,
                }));
                if (item.stroke) {
                    const strokeGrid = element('div', 'prop-grid');
                    look.append(strokeGrid);
                    row(strokeGrid, I18N.outline_color, colorInput(item.stroke, value => liveEdit(item, { stroke: value }), value => finalEdit(item, { stroke: value })));
                    row(strokeGrid, I18N.thickness, numberInput(item.strokeWidth, value => finalEdit(item, { strokeWidth: Math.max(1, value) }), { min: 1 }));
                }
                if (item.kind === 'rect') {
                    row(look, I18N.corner_radius, numberInput(item.radius, value => finalEdit(item, { radius: Math.max(0, value) }), { min: 0 }));
                }
                break;
            case 'line':
                row(look, I18N.color, colorInput(item.stroke, value => liveEdit(item, { stroke: value }), value => finalEdit(item, { stroke: value })));
                break;
            case 'label':
                row(look, I18N.text, textInput(item.text, value => liveEdit(item, { text: value }), value => finalEdit(item, { text: value }), true));
                row(look, I18N.font, selectInput(FONTS.map(font => ({ value: font.id, label: font.label })), item.font, value => finalEdit(item, { font: value })));
                {
                    const textGrid = element('div', 'prop-grid');
                    look.append(textGrid);
                    row(textGrid, I18N.font_size, numberInput(item.fontSize, value => finalEdit(item, { fontSize: Math.max(4, value) }), { min: 4 }));
                    row(textGrid, I18N.color, colorInput(item.color, value => liveEdit(item, { color: value }), value => finalEdit(item, { color: value })));
                }
                row(look, I18N.alignment, alignmentSelect(item));
                checkbox(look, I18N.bold, item.bold, value => finalEdit(item, { bold: value }));
                checkbox(look, I18N.italic, item.italic, value => finalEdit(item, { italic: value }));
                look.append(element('div', 'info-text', I18N.label_info));
                break;
            case 'photo': {
                const count = allElements(entry.design).filter(other => other.kind === 'photo').length;
                const options = Array.from({ length: count }, (_, index) => ({ value: index + 1, label: fmt(I18N.canvas_photo, { number: index + 1 }) }));
                row(look, I18N.photo_order, selectInput(options, item.number, value => {
                    const number = Number(value);
                    const other = allElements(entry.design).find(candidate => candidate.kind === 'photo' && candidate.number === number);
                    if (other) other.number = item.number;
                    item.number = number;
                    commit();
                }));
                look.append(element('div', 'info-text', I18N.photo_info));
                break;
            }
            case 'field': {
                const textArea = textInput(item.text, value => liveEdit(item, { text: value }), value => finalEdit(item, { text: value }), true);
                row(look, I18N.text, textArea);
                const placeholders = element('div', 'placeholder-buttons');
                [['{event}', I18N.placeholder_event_title], ['{date}', I18N.placeholder_date_title], ['{time}', I18N.placeholder_time_title]]
                    .forEach(([placeholder, title]) => {
                        const button = element('button', 'btn btn-secondary', placeholder);
                        button.type = 'button';
                        button.title = title;
                        button.addEventListener('click', () => {
                            const start = textArea.selectionStart ?? textArea.value.length;
                            const end = textArea.selectionEnd ?? textArea.value.length;
                            textArea.value = textArea.value.slice(0, start) + placeholder + textArea.value.slice(end);
                            finalEdit(item, { text: textArea.value });
                            textArea.focus();
                            textArea.selectionStart = textArea.selectionEnd = start + placeholder.length;
                        });
                        placeholders.append(button);
                    });
                look.append(placeholders);
                {
                    const textGrid = element('div', 'prop-grid');
                    textGrid.style.marginTop = '10px';
                    look.append(textGrid);
                    row(textGrid, I18N.color, colorInput(item.color, value => liveEdit(item, { color: value }), value => finalEdit(item, { color: value })));
                    row(textGrid, I18N.alignment, alignmentSelect(item));
                }
                checkbox(look, I18N.bold, item.bold, value => finalEdit(item, { bold: value }));
                look.append(element('div', 'info-text', I18N.field_info));
                break;
            }
            default:
                break;
        }

        buttons(panel, [
            { label: I18N.duplicate, onClick: duplicateSelection },
            { label: I18N.delete, className: 'btn-danger', onClick: deleteSelection },
        ]);
        if (locked) panel.append(element('div', 'info-text', I18N.level_locked_info));
    }

    function alignmentSelect(item) {
        return selectInput([
            { value: 'left', label: I18N.text_left },
            { value: 'center', label: I18N.text_center },
            { value: 'right', label: I18N.text_right },
        ], item.align, value => finalEdit(item, { align: value }));
    }

    function fitToPage(item, page) {
        const ratio = item.width / item.height;
        let width = page.width;
        let height = width / ratio;
        if (height < page.height) {
            height = page.height;
            width = height * ratio;
        }
        return { width, height, x: (page.width - width) / 2, y: (page.height - height) / 2, angle: 0 };
    }

    function markDirty(entry) {
        if (!entry.dirty) {
            entry.dirty = true;
            renderTemplateList();
        }
    }

    // --- the toolbar and the page -------------------------------------------

    document.querySelectorAll('[data-icon]').forEach(button => {
        button.insertAdjacentHTML('afterbegin', icon(button.dataset.icon));
    });

    function updateToolbar() {
        const entry = currentEntry();
        const selected = canvas.getActiveObjects().length;
        byId('undoButton').disabled = !entry || entry.history.index === 0;
        byId('redoButton').disabled = !entry || entry.history.index >= entry.history.states.length - 1;
        document.querySelectorAll('[data-add], #zoomInButton, #zoomOutButton, #fitButton, #previewButton, #saveButton, #exportButton')
            .forEach(button => { button.disabled = !entry; });
        document.querySelectorAll('[data-align]').forEach(button => { button.disabled = !selected; });
        document.querySelectorAll('[data-distribute]').forEach(button => { button.disabled = selected < 3; });
        updatePageControls();
        updateStatus();
    }

    let statusMessage = null;
    let statusTimer = null;

    function showStatus(message) {
        statusMessage = message;
        clearTimeout(statusTimer);
        statusTimer = setTimeout(() => {
            statusMessage = null;
            updateStatus();
        }, 4000);
        updateStatus();
    }

    function updateStatus() {
        const entry = currentEntry();
        const bar = byId('statusBar');
        bar.hidden = !entry;
        if (!entry) return;
        bar.textContent = statusMessage || I18N.status_hint;
    }

    function detectFormat(page) {
        const long = Math.max(page.width, page.height);
        const short = Math.min(page.width, page.height);
        for (const [name, preset] of Object.entries(PRESET_FORMATS)) {
            if (preset.long === long && preset.short === short) return name;
        }
        return 'custom';
    }

    function sizeInCm(width, height) {
        const cm = pixels => (Math.round(pixels / TEMPLATE_DPI * 2.54 * 10) / 10).toLocaleString(document.documentElement.lang || undefined);
        return width > 0 && height > 0 ? `≈ ${cm(width)} × ${cm(height)} cm` : '';
    }

    function pageSizeIsAllowed(width, height) {
        const limits = CONFIG.pageLimits;
        return Number.isInteger(width) && Number.isInteger(height) && width >= 1 && height >= 1
            && width <= limits.side && height <= limits.side && width * height <= limits.pixels;
    }

    function alertPageTooLarge() {
        alert(fmt(I18N.page_too_large, {
            side: CONFIG.pageLimits.side.toLocaleString(),
            pixels: CONFIG.pageLimits.pixels.toLocaleString(),
        }));
    }

    function updatePageControls() {
        const entry = currentEntry();
        const controls = ['orientationSelect', 'formatSelect', 'widthInput', 'heightInput', 'duplicateHorizontal', 'duplicateVertical'];
        controls.forEach(id => { byId(id).disabled = !entry; });
        if (!entry) return;
        const page = entry.template.page;
        const format = entry.customFormat ? 'custom' : detectFormat(page);
        byId('orientationSelect').value = page.width > page.height ? 'landscape' : 'portrait';
        byId('formatSelect').value = format;
        byId('widthInput').value = page.width;
        byId('heightInput').value = page.height;
        byId('widthInput').disabled = format !== 'custom';
        byId('heightInput').disabled = format !== 'custom';
        byId('sizeCm').textContent = sizeInCm(page.width, page.height);
        byId('duplicateHorizontal').checked = !!entry.template.duplicate_horizontal;
        byId('duplicateVertical').checked = !!entry.template.duplicate_vertical;
    }

    function resizePage(width, height) {
        const entry = currentEntry();
        entry.template.page = { width, height };
        commit();
        fitView();
    }

    byId('formatSelect').addEventListener('change', () => {
        const entry = currentEntry();
        const format = byId('formatSelect').value;
        if (format === 'custom') {
            entry.customFormat = true;
            updatePageControls();
            byId('widthInput').focus();
            return;
        }
        entry.customFormat = false;
        const preset = PRESET_FORMATS[format];
        const landscape = byId('orientationSelect').value === 'landscape';
        resizePage(landscape ? preset.long : preset.short, landscape ? preset.short : preset.long);
    });

    byId('orientationSelect').addEventListener('change', () => {
        const page = currentEntry().template.page;
        const landscape = byId('orientationSelect').value === 'landscape';
        if (landscape === page.width > page.height) return;
        resizePage(page.height, page.width);
    });

    function onPageSizeTyped() {
        const width = Number(byId('widthInput').value);
        const height = Number(byId('heightInput').value);
        if (!pageSizeIsAllowed(width, height)) {
            alertPageTooLarge();
            updatePageControls();
            return;
        }
        currentEntry().customFormat = true;
        resizePage(width, height);
    }

    byId('widthInput').addEventListener('change', onPageSizeTyped);
    byId('heightInput').addEventListener('change', onPageSizeTyped);
    ['widthInput', 'heightInput', 'gridSizeInput'].forEach(id => commitOnEnter(byId(id)));

    ['duplicateHorizontal', 'duplicateVertical'].forEach(id => {
        byId(id).addEventListener('change', () => {
            const entry = currentEntry();
            const horizontal = id === 'duplicateHorizontal';
            const checked = byId(id).checked;
            // Printed twice one way or the other, not both.
            entry.template.duplicate_horizontal = horizontal ? checked : (checked ? false : entry.template.duplicate_horizontal);
            entry.template.duplicate_vertical = horizontal ? (checked ? false : entry.template.duplicate_vertical) : checked;
            commit();
        });
    });

    byId('gridToggle').addEventListener('change', () => {
        state.gridEnabled = byId('gridToggle').checked;
        canvas.requestRenderAll();
    });

    byId('gridSizeInput').addEventListener('change', () => {
        const size = Number(byId('gridSizeInput').value);
        if (size >= 5 && size <= 200) {
            state.gridSize = size;
            canvas.requestRenderAll();
        }
    });

    byId('undoButton').addEventListener('click', undo);
    byId('redoButton').addEventListener('click', redo);
    byId('zoomInButton').addEventListener('click', () => zoomAtCentre(1.25));
    byId('zoomOutButton').addEventListener('click', () => zoomAtCentre(0.8));
    byId('fitButton').addEventListener('click', fitView);
    byId('addLevelButton').addEventListener('click', addLevel);

    document.querySelectorAll('[data-add]').forEach(button => {
        button.addEventListener('click', () => {
            if (button.dataset.add === 'image') byId('imageFile').click();
            else addElement(button.dataset.add);
        });
    });
    byId('imageFile').addEventListener('change', () => {
        addImageFiles(byId('imageFile').files);
        byId('imageFile').value = '';
    });
    document.querySelectorAll('[data-align]').forEach(button => {
        button.addEventListener('click', () => align(button.dataset.align));
    });
    document.querySelectorAll('[data-distribute]').forEach(button => {
        button.addEventListener('click', () => distribute(button.dataset.distribute));
    });

    canvasArea.addEventListener('dragover', event => {
        if (!currentEntry() || ![...event.dataTransfer.types].includes('Files')) return;
        event.preventDefault();
        canvasArea.classList.add('dropping');
    });
    canvasArea.addEventListener('dragleave', () => canvasArea.classList.remove('dropping'));
    canvasArea.addEventListener('drop', event => {
        canvasArea.classList.remove('dropping');
        if (!currentEntry() || !event.dataTransfer.files.length) return;
        event.preventDefault();
        addImageFiles(event.dataTransfer.files);
    });

    // --- keyboard -----------------------------------------------------------

    function typingSomewhere() {
        const active = document.activeElement;
        if (active && (['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) || active.isContentEditable)) return true;
        const object = canvas.getActiveObject();
        return !!(object && object.isEditing);
    }

    document.addEventListener('keydown', event => {
        if (event.key === ' ' && !typingSomewhere()) {
            if (!spaceHeld) {
                spaceHeld = true;
                canvasArea.classList.add('space-held');
            }
            event.preventDefault();
            return;
        }
        const modifier = event.ctrlKey || event.metaKey;
        if (modifier && event.key.toLowerCase() === 's') {
            event.preventDefault();
            saveCurrent();
            return;
        }
        if (typingSomewhere() || state.busy || !currentEntry()) return;
        const key = event.key.toLowerCase();

        if (modifier && key === 'z') {
            event.preventDefault();
            if (event.shiftKey) redo();
            else undo();
        } else if (modifier && key === 'y') {
            event.preventDefault();
            redo();
        } else if (modifier && key === 'c') {
            copySelection();
        } else if (modifier && key === 'x') {
            copySelection();
            deleteSelection();
        } else if (modifier && key === 'd') {
            event.preventDefault();
            duplicateSelection();
        } else if (modifier && key === 'a') {
            event.preventDefault();
            const entry = currentEntry();
            state.selectedIds = entry.design.levels.filter(level => level.visible && !level.locked)
                .flatMap(level => level.elements.map(item => item.id));
            renderDesign();
            syncSelectionFromCanvas();
        } else if (modifier && (key === '+' || key === '=')) {
            event.preventDefault();
            zoomAtCentre(1.25);
        } else if (modifier && key === '-') {
            event.preventDefault();
            zoomAtCentre(0.8);
        } else if (modifier && key === '0') {
            event.preventDefault();
            fitView();
        } else if (key === 'delete' || key === 'backspace') {
            event.preventDefault();
            deleteSelection();
        } else if (key === 'escape') {
            canvas.discardActiveObject();
            canvas.requestRenderAll();
        } else if (key.startsWith('arrow')) {
            event.preventDefault();
            const step = event.shiftKey ? 10 : 1;
            nudgeSelection(key === 'arrowleft' ? -step : key === 'arrowright' ? step : 0,
                key === 'arrowup' ? -step : key === 'arrowdown' ? step : 0);
        }
    });

    document.addEventListener('keyup', event => {
        if (event.key === ' ') {
            spaceHeld = false;
            canvasArea.classList.remove('space-held');
        }
    });

    window.addEventListener('blur', () => {
        spaceHeld = false;
        canvasArea.classList.remove('space-held');
    });

    // An image on the clipboard becomes an image of the design; otherwise
    // what was copied in the editor is pasted, shifted so it shows.
    document.addEventListener('paste', event => {
        if (typingSomewhere() || state.busy || !currentEntry()) return;
        const files = [...(event.clipboardData ? event.clipboardData.files : [])].filter(file => file.type.startsWith('image/'));
        event.preventDefault();
        if (files.length) addImageFiles(files);
        else pasteElements(state.clipboard, 30);
    });

    // --- templates: list, new, import, export -------------------------------

    function isDraft(entry) {
        return !entry.filename;
    }

    function renderTemplateList() {
        const list = byId('templateList');
        list.replaceChildren();

        const title = text => list.append(element('div', 'template-section-title', text));
        const note = text => list.append(element('div', 'template-list-note', text));

        title(I18N.section_booth);
        const booth = state.entries.filter(entry => !isDraft(entry));
        if (state.boothLoadError) note(fmt(I18N.booth_load_failed, { error: state.boothLoadError }));
        else if (!booth.length) note(I18N.booth_empty);
        booth.forEach(entry => list.append(templateListItem(entry)));

        const drafts = state.entries.filter(isDraft);
        if (drafts.length) {
            title(I18N.section_drafts);
            drafts.forEach(entry => list.append(templateListItem(entry)));
        }
    }

    function templateListItem(entry) {
        const index = state.entries.indexOf(entry);
        const item = element('div', `template-item${isDraft(entry) ? ' draft' : ''}${index === state.current ? ' active' : ''}`);
        item.addEventListener('click', () => selectTemplate(index));

        // Names, descriptions and file names come from template files: text
        // only, never markup, or a crafted template would run script with the
        // admin session that opened this editor.
        const meta = element('div', 'template-item-meta');
        const name = element('div', 'template-item-name', entry.template.name || '');
        if (entry.dirty) {
            const dot = element('span', 'dirty', '●');
            dot.title = I18N.unsaved_changes;
            name.append(dot);
        }
        meta.append(name, element('div', 'template-item-desc', entry.template.description || ''));
        if (!isDraft(entry)) meta.append(element('div', 'template-item-file', `templates/${entry.filename}`));

        const actions = element('div', 'template-item-actions');
        actions.append(
            rowButton('copy', I18N.duplicate_template, () => duplicateTemplate(index)),
            rowButton('trash', I18N.delete_template, () => deleteTemplate(index)),
        );
        item.append(meta, actions);
        return item;
    }

    function selectTemplate(index) {
        state.current = index;
        state.selectedIds = [];
        const entry = currentEntry();
        if (entry) {
            openEntry(entry);
            state.activeLevelId = entry.design.levels[entry.design.levels.length - 1].id;
        }
        renderAll();
        fitView();
        if (entry) loadFonts(entry.design).then(scheduleRender);
    }

    function renderAll() {
        renderTemplateList();
        renderDesign();
        renderLevels();
        renderProperties();
        updateToolbar();
    }

    function addEntry(entry) {
        state.entries.push(entry);
        selectTemplate(state.entries.length - 1);
    }

    function duplicateTemplate(index) {
        const source = state.entries[index];
        openEntry(source);
        const entry = makeEntry(source.template, null);
        entry.template.name = fmt(I18N.copy_name, { name: source.template.name });
        entry.template.design = clone(source.design);
        entry.dirty = true;
        addEntry(entry);
    }

    async function deleteTemplate(index) {
        const entry = state.entries[index];
        const boothCount = state.entries.filter(candidate => !isDraft(candidate)).length;
        if (!isDraft(entry) && boothCount <= 1) {
            alert(I18N.keep_one_template);
            return;
        }
        const message = isDraft(entry)
            ? fmt(I18N.confirm_delete, { name: entry.template.name })
            : fmt(I18N.confirm_delete_with_file, { name: entry.template.name, file: entry.filename });
        if (!confirm(message)) return;

        try {
            if (!isDraft(entry)) {
                const response = await fetch(`/api/templates/${encodeURIComponent(entry.filename)}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                cleanUpAssets();
            }
        } catch (error) {
            alert(fmt(I18N.delete_failed, { error: error.message }));
            return;
        }

        state.entries.splice(index, 1);
        if (index < state.current || state.current >= state.entries.length) state.current -= 1;
        if (state.current >= 0) {
            selectTemplate(state.current);
        } else {
            renderAll();
        }
    }

    function cleanUpAssets() {
        fetch('/api/template-assets/cleanup', { method: 'POST' }).catch(() => {});
    }

    const STARTERS = {
        empty_landscape: () => ({ page: { width: 1800, height: 1200 }, photos: [], print_params: PRINT_10X15 }),
        empty_portrait: () => ({ page: { width: 1200, height: 1800 }, photos: [], print_params: PRINT_10X15 }),
        empty_strip: () => ({ page: { width: 600, height: 1800 }, photos: [], print_params: PRINT_STRIP, duplicate_horizontal: true }),
        full_landscape: () => ({ page: { width: 1800, height: 1200 }, photos: [{ x: 60, y: 60, width: 1680, height: 1080 }], print_params: PRINT_10X15 }),
        full_portrait: () => ({ page: { width: 1200, height: 1800 }, photos: [{ x: 60, y: 60, width: 1080, height: 1680 }], print_params: PRINT_10X15 }),
        strip_portrait: () => ({
            page: { width: 600, height: 1800 },
            photos: [
                { x: 30, y: 30, width: 540, height: 540 },
                { x: 30, y: 600, width: 540, height: 540 },
                { x: 30, y: 1170, width: 540, height: 540 },
            ],
            print_params: PRINT_STRIP,
            duplicate_horizontal: true,
        }),
        strip_landscape: () => ({
            page: { width: 1800, height: 600 },
            photos: [
                { x: 30, y: 30, width: 540, height: 540 },
                { x: 630, y: 30, width: 540, height: 540 },
                { x: 1230, y: 30, width: 540, height: 540 },
            ],
            print_params: PRINT_STRIP,
            duplicate_vertical: true,
        }),
        custom: () => ({ page: readNewTemplateSize(), photos: [], print_params: PRINT_10X15 }),
    };

    function readNewTemplateSize() {
        return { width: Number(byId('newTemplateWidth').value), height: Number(byId('newTemplateHeight').value) };
    }

    function updateNewTemplateStarter() {
        const custom = byId('newTemplateStarter').value === 'custom';
        byId('newTemplateSizeGroup').hidden = !custom;
        const size = readNewTemplateSize();
        byId('newTemplateSizeCm').textContent = sizeInCm(size.width, size.height);
    }

    function openNewTemplateDialog() {
        byId('newTemplateName').value = '';
        byId('newTemplateDesc').value = '';
        updateNewTemplateStarter();
        byId('newTemplateModal').classList.add('show');
        byId('newTemplateName').focus();
    }

    function closeNewTemplateDialog() {
        byId('newTemplateModal').classList.remove('show');
    }

    byId('newTemplateButton').addEventListener('click', openNewTemplateDialog);
    byId('cancelNewTemplate').addEventListener('click', closeNewTemplateDialog);
    byId('newTemplateStarter').addEventListener('change', updateNewTemplateStarter);
    byId('newTemplateWidth').addEventListener('input', updateNewTemplateStarter);
    byId('newTemplateHeight').addEventListener('input', updateNewTemplateStarter);
    byId('confirmNewTemplate').addEventListener('click', () => {
        const starterName = byId('newTemplateStarter').value;
        const starter = clone(STARTERS[starterName]());
        if (!pageSizeIsAllowed(starter.page.width, starter.page.height)) {
            alertPageTooLarge();
            return;
        }
        const entry = makeEntry(Object.assign({
            name: byId('newTemplateName').value.trim() || I18N.new_template_name,
            description: byId('newTemplateDesc').value.trim(),
            texts: [],
            margin_percent: 5,
            duplicate_horizontal: false,
            duplicate_vertical: false,
        }, starter), null);
        entry.dirty = true;
        closeNewTemplateDialog();
        addEntry(entry);
        if (starterName === 'custom') {
            entry.customFormat = true;
            entry.history = { states: [snapshot(entry)], index: 0 };
            updatePageControls();
        }
    });

    byId('importButton').addEventListener('click', () => byId('importJsonFile').click());
    byId('importJsonFile').addEventListener('change', () => {
        const file = byId('importJsonFile').files[0];
        byId('importJsonFile').value = '';
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
            let data;
            try {
                data = JSON.parse(reader.result);
            } catch (error) {
                alert(fmt(I18N.parse_failed, { error: error.message }));
                return;
            }
            if (!isObject(data) || typeof data.name !== 'string' || !isObject(data.page)
                || !pageSizeIsAllowed(data.page.width, data.page.height)) {
                alert(I18N.invalid_file);
                return;
            }
            const entry = makeEntry(data, null);
            entry.dirty = true;
            addEntry(entry);
            showStatus(fmt(I18N.imported, { name: data.name }));
        };
        reader.readAsText(file);
    });

    // --- flattening for the booth -------------------------------------------

    function blobToDataUrl(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
    }

    function canvasToBlob(source, type, quality) {
        return new Promise(resolve => source.toBlob(resolve, type, quality));
    }

    // Images still carried inside the design (an old template's layers, an
    // imported file) go to the booth's assets first: the design keeps a
    // reference, never the pixels.
    async function uploadEmbeddedImages(entry) {
        const uploaded = new Map();
        for (const item of allElements(entry.design)) {
            if (item.kind !== 'image' || !/^data:/i.test(item.src)) continue;
            if (!uploaded.has(item.src)) {
                const blob = await (await fetch(item.src)).blob();
                const asset = await uploadImageBlob(blob, 'image');
                uploaded.set(item.src, asset.filename);
                await loadImage(asset.filename);
            }
            item.src = uploaded.get(item.src);
        }
    }

    // One run of decoration drawn alone on a transparent page, cropped to what
    // it covers. Returns null when it covers nothing.
    function renderRun(run, page, scale) {
        const surface = document.createElement('canvas');
        const width = Math.round(page.width * scale);
        const height = Math.round(page.height * scale);
        const staticCanvas = new fabric.StaticCanvas(surface, {
            width, height, enableRetinaScaling: false, renderOnAddRemove: false,
        });
        staticCanvas.setViewportTransform([scale, 0, 0, scale, 0, 0]);
        run.forEach(({ item, level }) => {
            const object = buildObject(item, level.opacity, 'export');
            if (object) staticCanvas.add(object);
        });
        staticCanvas.renderAll();

        const pixels = staticCanvas.getContext().getImageData(0, 0, width, height).data;
        let minX = width;
        let minY = height;
        let maxX = -1;
        let maxY = -1;
        let opaquePixels = 0;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const alpha = pixels[(y * width + x) * 4 + 3];
                if (!alpha) continue;
                if (alpha === 255) opaquePixels++;
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
        if (maxX < 0) {
            staticCanvas.dispose();
            return null;
        }

        // Whole template pixels, so the booth draws the image exactly over
        // the area it was cut from.
        const left = Math.floor(minX / scale);
        const top = Math.floor(minY / scale);
        const right = Math.min(page.width, Math.ceil((maxX + 1) / scale));
        const bottom = Math.min(page.height, Math.ceil((maxY + 1) / scale));
        const cropped = document.createElement('canvas');
        cropped.width = Math.round((right - left) * scale);
        cropped.height = Math.round((bottom - top) * scale);
        cropped.getContext('2d').drawImage(surface, Math.round(left * scale), Math.round(top * scale),
            cropped.width, cropped.height, 0, 0, cropped.width, cropped.height);
        staticCanvas.dispose();

        return {
            canvas: cropped,
            box: { x: left, y: top, width: right - left, height: bottom - top },
            opaque: opaquePixels === cropped.width * cropped.height,
        };
    }

    async function flushRun(run, page, stack) {
        if (!run.length) return;
        const largest = Math.max(page.width, page.height);
        const sharpest = Math.min(FLATTEN_SCALE, MAX_CANVAS_SIDE / largest);
        // Sharpest first; a photographic background too heavy for the booth
        // at 600 dpi is sent at the template's own resolution instead.
        for (const scale of sharpest > 1 ? [sharpest, 1] : [sharpest]) {
            const rendered = renderRun(run, page, scale);
            if (!rendered) return;
            // Nothing see-through: a JPEG is a fraction of the PNG's weight.
            const blob = rendered.opaque
                ? await canvasToBlob(rendered.canvas, 'image/jpeg', 0.92)
                : await canvasToBlob(rendered.canvas, 'image/png');
            if (blob.size > CONFIG.assetBytesLimit && scale !== 1 && sharpest > 1) continue;
            const asset = await uploadImageBlob(blob, rendered.opaque ? 'level.jpg' : 'level.png');
            stack.push(Object.assign({ type: 'image', src: asset.filename, opacity: 1 }, rendered.box));
            return;
        }
    }

    async function buildBoothTemplate(entry) {
        const design = entry.design;
        const page = entry.template.page;
        await uploadEmbeddedImages(entry);
        await Promise.all(allElements(design).filter(item => item.kind === 'image').map(item => loadImage(item.src)));
        await loadFonts(design);

        const missing = allElements(design).filter(item => item.kind === 'image' && !readyImage(item.src));
        if (missing.length) throw new Error(I18N.images_missing_error);

        const slots = allElements(design).filter(item => item.kind === 'photo').sort((a, b) => a.number - b.number);
        if (!slots.length) throw new Error(I18N.no_photo_slot);

        const texts = [];
        const stack = [];
        let run = [];
        for (const level of design.levels) {
            for (const item of level.elements) {
                const opacity = roundTo(item.opacity * level.opacity, 3);
                if (SLOT_KINDS.includes(item.kind)) {
                    if (!level.visible) throw new Error(fmt(I18N.hidden_slot_error, { level: level.name }));
                    await flushRun(run, page, stack);
                    run = [];
                    clampSlot(item, page);
                    if (item.kind === 'photo') {
                        stack.push({ type: 'photo', index: slots.indexOf(item), opacity });
                    } else {
                        texts.push({
                            x: item.x, y: item.y, width: item.width, height: item.height,
                            text: item.text, color: item.color, align: item.align, bold: item.bold,
                        });
                        stack.push({ type: 'text', index: texts.length - 1, opacity });
                    }
                } else if (level.visible && opacity > 0) {
                    run.push({ item, level });
                }
            }
        }
        await flushRun(run, page, stack);
        if (stack.length > CONFIG.stackLimit) {
            throw new Error(fmt(I18N.too_many_layers, { limit: CONFIG.stackLimit }));
        }

        const savedDesign = clone(design);
        savedDesign.levels.forEach(level => {
            delete level.id;
            level.elements.forEach(item => { delete item.id; delete item.lastFill; });
        });

        return {
            name: (entry.template.name || '').trim() || I18N.new_template_name,
            description: (entry.template.description || '').trim(),
            page: clone(page),
            photos: slots.map(item => ({ x: item.x, y: item.y, width: item.width, height: item.height })),
            texts,
            stack,
            background: null,
            foreground: null,
            print_params: clone(entry.template.print_params || PRINT_10X15),
            margin_percent: finite(entry.template.margin_percent, 5),
            duplicate_horizontal: !!entry.template.duplicate_horizontal,
            duplicate_vertical: !!entry.template.duplicate_vertical,
            design: savedDesign,
        };
    }

    function setBusy(message) {
        state.busy = !!message;
        byId('busy').hidden = !message;
        byId('busyMessage').textContent = message || '';
    }

    async function saveCurrent() {
        const entry = currentEntry();
        if (!entry || state.busy) return;
        if (canvas.getActiveObject() && canvas.getActiveObject().isEditing) canvas.getActiveObject().exitEditing();
        setBusy(I18N.saving);
        try {
            const template = await buildBoothTemplate(entry);
            const response = await fetch('/api/templates', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: entry.filename, template }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            entry.filename = payload.filename || entry.filename;
            entry.template = Object.assign(template, { design: null });
            entry.dirty = false;
            cleanUpAssets();
            renderAll();
            showStatus(fmt(I18N.saved, { file: entry.filename }));
        } catch (error) {
            alert(fmt(I18N.save_failed, { error: error.message }));
        } finally {
            setBusy(null);
        }
    }

    async function previewCurrent() {
        const entry = currentEntry();
        if (!entry || state.busy) return;
        setBusy(I18N.preparing_preview);
        try {
            const template = await buildBoothTemplate(entry);
            const response = await fetch('/api/templates/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ template }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            const boothImage = byId('previewBoothImage');
            if (boothImage.src.startsWith('blob:')) URL.revokeObjectURL(boothImage.src);
            boothImage.src = URL.createObjectURL(await response.blob());
            byId('previewEditorImage').src = editorSnapshot(entry);
            byId('previewModal').classList.add('show');
        } catch (error) {
            alert(fmt(I18N.preview_failed, { error: error.message }));
        } finally {
            setBusy(null);
            renderDesign();
        }
    }

    // The page as the editor draws it, without selection or badges' veil.
    function editorSnapshot(entry) {
        const page = entry.template.page;
        const scale = Math.min(1, 1200 / Math.max(page.width, page.height));
        const surface = document.createElement('canvas');
        const staticCanvas = new fabric.StaticCanvas(surface, {
            width: Math.round(page.width * scale), height: Math.round(page.height * scale),
            enableRetinaScaling: false, renderOnAddRemove: false, backgroundColor: '#ffffff',
        });
        staticCanvas.setViewportTransform([scale, 0, 0, scale, 0, 0]);
        entry.design.levels.filter(level => level.visible).forEach(level => {
            level.elements.forEach(item => {
                const object = buildObject(item, level.opacity, 'snapshot');
                if (object) staticCanvas.add(object);
            });
        });
        staticCanvas.renderAll();
        const url = surface.toDataURL('image/png');
        staticCanvas.dispose();
        return url;
    }

    byId('closePreview').addEventListener('click', () => byId('previewModal').classList.remove('show'));
    byId('saveButton').addEventListener('click', saveCurrent);
    byId('previewButton').addEventListener('click', previewCurrent);

    // Exported as one file another booth can take as it is: every image the
    // template uses is carried inside it.
    byId('exportButton').addEventListener('click', async () => {
        const entry = currentEntry();
        if (!entry || state.busy) return;
        setBusy(I18N.exporting);
        try {
            const template = await buildBoothTemplate(entry);
            const inline = new Map();
            const embed = async src => {
                const url = imageUrl(src);
                if (!url || url.startsWith('data:')) return src;
                if (!inline.has(url)) inline.set(url, await blobToDataUrl(await (await fetch(url)).blob()));
                return inline.get(url);
            };
            for (const layer of template.stack) {
                if (layer.type === 'image') layer.src = await embed(layer.src);
            }
            for (const level of template.design.levels) {
                for (const item of level.elements) {
                    if (item.kind === 'image') item.src = await embed(item.src);
                }
            }
            const blob = new Blob([JSON.stringify(template, null, 2)], { type: 'application/json' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `${(template.name || 'template').toLowerCase().replace(/[^a-z0-9_-]+/gi, '_')}.json`;
            document.body.append(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        } catch (error) {
            alert(fmt(I18N.export_failed, { error: error.message }));
        } finally {
            setBusy(null);
            renderDesign();
        }
    });

    window.addEventListener('beforeunload', event => {
        if (state.entries.some(entry => entry.dirty)) {
            event.preventDefault();
            event.returnValue = '';
        }
    });

    // Fonts arrive after the first drawing; text measured in a fallback font
    // is measured again once the real one is there.
    document.fonts.addEventListener('loadingdone', () => {
        if (fabric.cache && fabric.cache.clearFontCache) fabric.cache.clearFontCache();
        scheduleRender();
    });

    // --- start --------------------------------------------------------------

    async function init() {
        try {
            const response = await fetch('/api/templates');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (isObject(payload.text_values)) state.textValues = payload.text_values;
            (Array.isArray(payload.templates) ? payload.templates : []).forEach(item => {
                if (isObject(item) && isObject(item.template) && isObject(item.template.page) && item.filename) {
                    state.entries.push(makeEntry(item.template, item.filename));
                }
            });
        } catch (error) {
            state.boothLoadError = error.message;
        }

        if (state.entries.length) {
            selectTemplate(0);
        } else {
            renderAll();
            if (!state.boothLoadError) openNewTemplateDialog();
        }
    }

    init();
})();
