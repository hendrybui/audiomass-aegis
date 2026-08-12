(function ( w ) {
	'use strict';

	function scoreLag ( flux, lag ) {
		var score = 0;
		var len = flux.length - lag;
		if (len <= 0) return (0);

		for (var i = lag; i < flux.length; ++i)
			score += flux[i] * flux[i - lag];

		return (score / len);
	}

	function makeFlux ( buffer ) {
		var sr = buffer.sampleRate;
		var hop = Math.max (256, (sr / 100) >> 0);
		var frames = Math.max (1, buffer.length / hop >> 0);
		var env = new Float32Array (frames);
		var chans = buffer.numberOfChannels;
		var ch0 = buffer.getChannelData (0);
		var ch1 = chans > 1 ? buffer.getChannelData (1) : null;

		for (var i = 0; i < frames; ++i) {
			var start = i * hop;
			var end = Math.min (buffer.length, start + hop);
			var sum = 0;
			var j = start;

			if (ch1) {
				for (; j < end; ++j)
					sum += Math.abs (ch0[j]) + Math.abs (ch1[j]);
				env[i] = sum / ((end - start) * 2);
			}
			else {
				for (; j < end; ++j)
					sum += Math.abs (ch0[j]);
				env[i] = sum / (end - start);
			}
		}

		var flux = new Float32Array (frames);
		var mean = env[0] || 0;
		flux[0] = mean;
		for (i = 1; i < frames; ++i) {
			var v = env[i] - env[i - 1];
			if (v > 0) {
				flux[i] = v;
				mean += v;
			}
		}

		mean = mean / Math.max (1, frames) * 1.25;
		for (i = 0; i < frames; ++i)
			flux[i] = Math.max (0, flux[i] - mean);

		return ({ data: flux, rate: sr / hop });
	}

	function foldTempo ( bpm, min, max ) {
		while (bpm < min) bpm *= 2;
		while (bpm > max) bpm /= 2;
		return (bpm);
	}

	function pickPeaks ( flux, rate ) {
		var peaks = [];
		var hold = Math.max (1, rate * 0.08 >> 0);
		var last = -hold;

		for (var i = 1; i < flux.length - 1; ++i) {
			if (i - last < hold) continue;
			if (flux[i] <= flux[i - 1] || flux[i] < flux[i + 1] || flux[i] <= 0)
				continue;

			peaks.push ({ pos: i, val: flux[i] });
			last = i;
		}

		peaks.sort (function ( a, b ) { return b.val - a.val; });
		if (peaks.length > 320) peaks.length = 320;
		peaks.sort (function ( a, b ) { return a.pos - b.pos; });
		return (peaks);
	}

	function intervalTempo ( flux, rate, min, max ) {
		var peaks = pickPeaks (flux, rate);
		var bins = {};
		var best = 0;
		var bestScore = 0;
		var second = 0;

		for (var i = 0; i < peaks.length; ++i) {
			for (var j = i + 1; j < peaks.length && j < i + 16; ++j) {
				var dist = (peaks[j].pos - peaks[i].pos) / rate;
				if (dist <= 0) continue;
				var bpm = foldTempo (60 / dist, min, max);
				var key = Math.round (bpm);
				var score = (peaks[i].val + peaks[j].val) / (j - i);

				bins[key] = (bins[key] || 0) + score;
			}
		}

		for (var k in bins) {
			var val = bins[k];
			if (val > bestScore) {
				second = bestScore;
				bestScore = val;
				best = k / 1;
			}
			else if (val > second) {
				second = val;
			}
		}

		return ({
			tempo: best,
			score: bestScore,
			confidence: bestScore ? (bestScore - second) / bestScore : 0
		});
	}

	function analyze ( buffer, opts ) {
		opts = opts || {};
		if (!buffer || !buffer.length || buffer.duration < 2)
			throw new Error ('Audio is too short to estimate tempo.');

		var min = opts.minTempo || 60;
		var max = opts.maxTempo || 200;
		var env = makeFlux (buffer);
		var flux = env.data;
		var rate = env.rate;
		var minLag = Math.max (1, Math.round (rate * 60 / max));
		var maxLag = Math.min (flux.length - 1, Math.round (rate * 60 / min));
		var bestLag = 0;
		var bestScore = 0;
		var secondScore = 0;
		var rawBest = 0;
		var rawSecond = 0;

		for (var lag = minLag; lag <= maxLag; ++lag) {
			var score = scoreLag (flux, lag);
			if (lag * 2 < flux.length) score += scoreLag (flux, lag * 2) * 0.35;
			if (lag * 3 < flux.length) score += scoreLag (flux, lag * 3) * 0.20;

			if (score > rawBest) { rawSecond = rawBest; rawBest = score; }
			else if (score > rawSecond) rawSecond = score;

			// Tempo-preference prior (log-Gaussian near 120 BPM) resolves the
			// classic octave ambiguity (60 vs 120, 70 vs 140 ...) toward the
			// perceived beat instead of the strongest raw periodicity.
			var oct = Math.log2 ((60 * rate / lag) / 120) / 0.9;
			score *= Math.exp (-0.5 * oct * oct);

			if (score > bestScore) {
				secondScore = bestScore;
				bestScore = score;
				bestLag = lag;
			}
			else if (score > secondScore) {
				secondScore = score;
			}
		}

		if (!bestLag || !bestScore)
			throw new Error ('Could not find a reliable tempo.');

		var acTempo = 60 * rate / bestLag;
		var intv = intervalTempo (flux, rate, min, max);
		var tempo = acTempo;
		// The interval histogram is a weak signal on its own (it misfolds
		// offbeat-heavy tracks), so it only overrides when the autocorrelation
		// has no clear peak at all AND the interval evidence is very strong.
		var gap = bestScore > 0 ? (bestScore - secondScore) / bestScore : 0;
		if (intv.tempo && gap < 0.04 && intv.confidence > 0.5)
			tempo = intv.tempo;

		bestLag = Math.max (1, Math.round (rate * 60 / tempo));

		var phase = 0;
		var phaseScore = 0;
		for (var p = 0, phaseLen = Math.min (bestLag, flux.length); p < phaseLen; ++p) {
			var ps = 0;
			for (var k = p; k < flux.length; k += bestLag)
				ps += flux[k];

			if (ps > phaseScore) {
				phaseScore = ps;
				phase = p;
			}
		}

		var period = bestLag / rate;
		var offset = phase / rate;
		var beats = Math.max (0, Math.floor ((buffer.duration - offset) / period));
		var confidence = rawBest > 0 ? Math.max ((rawBest - rawSecond) / rawBest, gap) : 0;
		confidence = Math.max (0, Math.min (100, confidence * 100));

		var keyInfo = detectKey (buffer);

		return ({
			tempo: Math.round (tempo * 10) / 10,
			bpm: Math.round (tempo),
			offset: Math.round (offset * 1000) / 1000,
			beats: beats,
			confidence: Math.round (confidence),
			key: keyInfo.key,
			keyConfidence: keyInfo.confidence,
			duration: Math.round (buffer.duration * 10) / 10
		});
	}

var KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
var KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];
var NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

function fft ( re, im, n ) {
	for (var i = 1, j = 0; i < n; ++i) {
		var bit = n >> 1;
		for (; j & bit; bit >>= 1) j ^= bit;
		j ^= bit;
		if (i < j) {
			var tr = re[i]; re[i] = re[j]; re[j] = tr;
			var ti = im[i]; im[i] = im[j]; im[j] = ti;
		}
	}
	for (var len = 2; len <= n; len <<= 1) {
		var ang = -2 * Math.PI / len;
		var wr = Math.cos (ang), wi = Math.sin (ang);
		for (var base = 0; base < n; base += len) {
			var cwr = 1, cwi = 0;
			for (var k = 0; k < len / 2; ++k) {
				var ur = re[base + k], ui = im[base + k];
				var vr = re[base + k + len / 2] * cwr - im[base + k + len / 2] * cwi;
				var vi = re[base + k + len / 2] * cwi + im[base + k + len / 2] * cwr;
				re[base + k] = ur + vr; im[base + k] = ui + vi;
				re[base + k + len / 2] = ur - vr; im[base + k + len / 2] = ui - vi;
				var nwr = cwr * wr - cwi * wi;
				cwi = cwr * wi + cwi * wr;
				cwr = nwr;
			}
		}
	}
}

function detectKey ( buffer ) {
	if (!buffer || !buffer.length || !buffer.getChannelData) return ({ key: null, confidence: 0 });
	var sr = buffer.sampleRate || 44100;
	var step = Math.max (1, Math.round (sr / 22050));
	var maxLen = Math.min (buffer.length, Math.round (90 * sr));
	var ch0 = buffer.getChannelData (0);
	var ch1 = buffer.numberOfChannels > 1 ? buffer.getChannelData (1) : null;
	var monoLen = Math.ceil (maxLen / step);
	if (monoLen < 2048) return ({ key: null, confidence: 0 });
	var mono = new Float32Array (monoLen);
	for (var i = 0; i < monoLen; ++i) {
		var s = i * step;
		mono[i] = ch1 ? (ch0[s] + ch1[s]) * 0.5 : ch0[s];
	}
	var nsr = sr / step;
	var fftSize = 2048;
	var hop = 2048;
	var chroma = new Float32Array (12);
	var frames = 0;
	var re = new Float32Array (fftSize);
	var im = new Float32Array (fftSize);
	for (var pos = 0; pos + fftSize <= mono.length; pos += hop) {
		for (var j = 0; j < fftSize; ++j) {
			re[j] = mono[pos + j] * (0.5 - 0.5 * Math.cos (2 * Math.PI * j / (fftSize - 1)));
			im[j] = 0;
		}
		fft (re, im, fftSize);
		for (var b = 1; b < fftSize / 2; ++b) {
			var f = b * nsr / fftSize;
			if (f < 32 || f > 4000) continue;
			var pc = (Math.round (12 * Math.log2 (f / 440)) + 9) % 12;
			if (pc < 0) pc += 12;
			var mag = Math.sqrt (re[b] * re[b] + im[b] * im[b]);
			chroma[pc] += mag / f;
		}
		frames++;
	}
	if (!frames) return ({ key: null, confidence: 0 });
	var total = 0;
	for (var c = 0; c < 12; ++c) total += chroma[c];
	if (!total) return ({ key: null, confidence: 0 });
	for (c = 0; c < 12; ++c) chroma[c] /= total;
	var best = -1, second = -1, bestIdx = 0, bestMin = false;
	for (var mode = 0; mode < 2; ++mode) {
		var prof = mode === 0 ? KS_MAJOR : KS_MINOR;
		for (var root = 0; root < 12; ++root) {
			var score = 0;
			for (var k = 0; k < 12; ++k)
				score += chroma[(k + root) % 12] * prof[k];
			if (score > best) { second = best; best = score; bestIdx = root; bestMin = (mode === 1); }
			else if (score > second) second = score;
		}
	}
	var conf = second > 0 ? (best - second) / best : 0;
	return ({
		key: NOTE_NAMES[bestIdx] + ' ' + (bestMin ? 'minor' : 'major'),
		confidence: Math.max (0, Math.min (100, Math.round (conf * 100)))
	});
}

	w.PKTempoEstimator = {
		estimate: function ( buffer, opts ) {
			return new Promise (function ( resolve, reject ) {
				setTimeout (function () {
					try { resolve (analyze (buffer, opts)); }
					catch (e) { reject (e); }
				}, 20);
			});
		}
	};
	})( typeof self !== 'undefined' ? self : window );
