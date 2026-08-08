(function ( w, d, PKAE ) {
	'use strict';

	function PKStems ( app ) {
		var q = this;

		// Compute the API base relative to where this page is served from.
		// When AudioMass is reached directly (localhost:5055/) the base is '/api'.
		// When it's behind a path-prefixed reverse proxy (e.g. Caddy serving it
		// at /mass/ or /audiomass/), the base must include that prefix, otherwise
		// '/api/...' resolves to the proxy root and silently misses the backend.
		function detectApiBase () {
			var prefixMatch = d.location.pathname.match(/^(\/[a-z0-9_-]+)\//i);
			var prefix = prefixMatch ? prefixMatch[1] : '';
			return prefix + '/api';
		}

		var API_BASE = detectApiBase();
		var separating = false;
		var current_job_id = null;
		var event_source = null;

		// ---- Stem Settings ----
		var stemSettings = {
			selectedStems: ['vocals', 'drums', 'bass', 'other'],
			apiEndpoint: API_BASE,
			outputFormat: 'wav'
		};

		// Load settings from localStorage if available. NOTE: we intentionally do
		// NOT restore a previously-saved apiEndpoint here — it was often a stale
		// '/api' captured under direct access, which then breaks when the app is
		// later opened behind a proxy prefix. The auto-detected value above is
		// always correct for the current access path.
		var savedSettings = w.localStorage.getItem('audiomass_stem_settings');
		if (savedSettings) {
			try {
				var parsed = JSON.parse(savedSettings);
				// Guard against corrupted entries: only accept arrays/strings of
				// the right shape, otherwise we'd store a non-array into
				// selectedStems and crash later inside the Save callback loop.
				if (parsed && Array.isArray(parsed.selectedStems)) {
					stemSettings.selectedStems = parsed.selectedStems;
				}
				if (parsed && typeof parsed.outputFormat === 'string') {
					stemSettings.outputFormat = parsed.outputFormat;
				}
			} catch (e) {
				console.warn('Failed to load stem settings:', e);
			}
		}

		function saveStemSettings() {
			try {
				w.localStorage.setItem('audiomass_stem_settings', JSON.stringify(stemSettings));
			} catch (e) {
				console.warn('Failed to save stem settings:', e);
			}
		}

		q.getStemSettings = function() {
			return stemSettings;
		};

		q.setStemSettings = function(newSettings) {
			if (newSettings.selectedStems) stemSettings.selectedStems = newSettings.selectedStems;
			if (newSettings.apiEndpoint) {
				stemSettings.apiEndpoint = newSettings.apiEndpoint;
				API_BASE = newSettings.apiEndpoint;
			}
			if (newSettings.outputFormat) stemSettings.outputFormat = newSettings.outputFormat;
			saveStemSettings();
		};

		// ---- WAV encoding (reuse AudioMass wav.js helpers) ----
		function floatTo16BitPCM ( output, offset, input ) {
			for ( var i = 0; i < input.length; i++, offset += 2 ) {
				var s = Math.max( -1, Math.min( 1, input[i] ) );
				output.setInt16( offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true );
			}
		}

		function writeString ( view, offset, str ) {
			for ( var i = 0; i < str.length; i++ ) {
				view.setUint8( offset + i, str.charCodeAt( i ) );
			}
		}

		function audioBufferToWavBlob ( buffer ) {
			var numChannels = buffer.numberOfChannels;
			var sampleRate = buffer.sampleRate;
			var length = buffer.length;
			var channelData = [];
			for ( var c = 0; c < numChannels; c++ ) {
				channelData.push( buffer.getChannelData( c ) );
			}

			// interleave
			var interleaved = new Float32Array( length * numChannels );
			for ( var i = 0; i < length; i++ ) {
				for ( var ch = 0; ch < numChannels; ch++ ) {
					interleaved[ i * numChannels + ch ] = channelData[ ch ][ i ];
				}
			}

			// convert to 16-bit PCM
			var samples = new Int16Array( interleaved.length );
			for ( var j = 0; j < interleaved.length; j++ ) {
				var s = Math.max( -1, Math.min( 1, interleaved[j] ) );
				samples[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
			}

			var dataLength = samples.length * 2;
			var buf = new ArrayBuffer( 44 + dataLength );
			var view = new DataView( buf );

			writeString( view, 0, 'RIFF' );
			view.setUint32( 4, 36 + dataLength, true );
			writeString( view, 8, 'WAVE' );
			writeString( view, 12, 'fmt ' );
			view.setUint32( 16, 16, true );
			view.setUint16( 20, 1, true );
			view.setUint16( 22, numChannels, true );
			view.setUint32( 24, sampleRate, true );
			view.setUint32( 28, sampleRate * numChannels * 2, true );
			view.setUint16( 32, numChannels * 2, true );
			view.setUint16( 34, 16, true );
			writeString( view, 36, 'data' );
			view.setUint32( 40, dataLength, true );
			floatTo16BitPCM( view, 44, interleaved );

			return new Blob( [view], { type: 'audio/wav' } );
		}

		// ---- Get audio from editor ----
		function getAudioBuffer () {
			// Try multitrack selected clip first
		console.log('[Stem Separation] Checking multitrack for audio...');
			var mt = app.multitrack;
			if ( mt && mt.IsOn && mt.IsOn() ) {
				var state = mt.getState && mt.getState();
				if ( state && state.clips && state.clips.length > 0 ) {
					// mixdown all clips to a single buffer
					var mixdown = mt.Mixdown && mt.Mixdown();
					if ( mixdown ) return mixdown;
				}
			}

			// Check single-track editor
		console.log('[Stem Separation] Checking single-track editor for audio...');
			var wv = app.engine && app.engine.wavesurfer;
			if ( wv && wv.backend && wv.backend.buffer ) {
				return wv.backend.buffer;
			}

			return null;
		}

		// ---- Progress Modal ----
		var modal_el = null;
		var progress_bar = null;
		var stage_label = null;
		var cancel_btn = null;

		function showProgressModal () {
			if ( modal_el ) return;

			modal_el = d.createElement( 'div' );
			modal_el.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:99999;display:flex;align-items:center;justify-content:center;';

			var box = d.createElement( 'div' );
			box.style.cssText = 'background:#1a1a2e;color:#eee;border-radius:8px;padding:24px 32px;min-width:360px;box-shadow:0 8px 32px rgba(0,0,0,0.5);font-family:system-ui,sans-serif;';

			var title = d.createElement( 'h3' );
			title.textContent = 'Separating Stems';
			title.style.cssText = 'margin:0 0 16px 0;font-size:16px;color:#e94560;';

			stage_label = d.createElement( 'div' );
			stage_label.textContent = 'Preparing...';
			stage_label.style.cssText = 'margin-bottom:8px;font-size:13px;color:#aaa;';

			var bar_bg = d.createElement( 'div' );
			bar_bg.style.cssText = 'width:100%;height:8px;background:#333;border-radius:4px;overflow:hidden;margin-bottom:16px;';

			progress_bar = d.createElement( 'div' );
			progress_bar.style.cssText = 'width:0%;height:100%;background:linear-gradient(90deg,#e94560,#0f3460);transition:width 0.3s;border-radius:4px;';
			bar_bg.appendChild( progress_bar );

			cancel_btn = d.createElement( 'button' );
			cancel_btn.textContent = 'Cancel';
			cancel_btn.style.cssText = 'background:#333;color:#eee;border:1px solid #555;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;';
			cancel_btn.onclick = function () { cancelSeparation(); };

			box.appendChild( title );
			box.appendChild( stage_label );
			box.appendChild( bar_bg );
			box.appendChild( cancel_btn );
			modal_el.appendChild( box );
			d.body.appendChild( modal_el );
		}

		function updateProgress ( pct, stage ) {
			if ( progress_bar ) progress_bar.style.width = pct + '%';
			if ( stage_label ) stage_label.textContent = stage;
		}

		function hideProgressModal () {
			if ( modal_el && modal_el.parentNode ) {
				modal_el.parentNode.removeChild( modal_el );
			}
			modal_el = null;
			progress_bar = null;
			stage_label = null;
			cancel_btn = null;
		}

		// ---- SSE Progress ----
		function streamProgress ( jobId ) {
			event_source = new EventSource( API_BASE + '/jobs/' + jobId + '/events' );

			event_source.addEventListener( 'job_state', function ( e ) {
				try {
					var data = JSON.parse( e.data );
					if ( data.status === 'done' ) {
						// Job already completed - load stems immediately
						closeSSE();
						updateProgress( 100, 'Loading stems...' );
						loadStems( current_job_id );
					}
				} catch ( err ) {}
			});

			event_source.addEventListener( 'job_progress', function ( e ) {
				try {
					var data = JSON.parse( e.data );
					var pct = data.progress || 0;
					var stage = data.status || data.stage || 'Processing...';
					// Human-readable stage names
					var stageNames = {
						'validating_input': 'Validating audio...',
						'ingesting_source': 'Loading audio...',
						'transcoding': 'Converting format...',
						'separating': 'Separating stems (Demucs)...',
						'postprocessing': 'Post-processing...',
						'analyzing': 'Analyzing audio...',
						'packaging': 'Packaging results...'
					};
					var label = stageNames[stage] || stage;
					updateProgress( pct, label );
				} catch ( err ) {}
			});

			event_source.addEventListener( 'job_done', function ( e ) {
				closeSSE();
				updateProgress( 100, 'Loading stems...' );
				loadStems( jobId );
			});

			event_source.addEventListener( 'job_failed', function ( e ) {
				closeSSE();
				separating = false;
				hideProgressModal();
				var msg = 'Separation failed';
				try { var errData = JSON.parse(e.data); msg = errData.message || errData.error || errData.detail || msg; } catch(err){}
				OneUp && OneUp( msg, 3000 );
			});

			event_source.addEventListener( 'job_cancelled', function () {
				closeSSE();
				separating = false;
				hideProgressModal();
				OneUp && OneUp( 'Separation cancelled', 2000 );
			});

			event_source.onerror = function () {
				closeSSE();
			};
		}

		function closeSSE () {
			if ( event_source ) {
				event_source.close();
				event_source = null;
			}
		}

		// ---- Load stems into multitrack ----
		function loadStems ( jobId ) {
			fetch( API_BASE + '/jobs/' + jobId + '/manifest' )
				.then( function ( r ) { return r.json(); } )
				.then( function ( manifest ) {
					var stemNames = manifest.selected_stems || manifest.available_stems || [];
					if ( !stemNames.length ) {
						separating = false;
						hideProgressModal();
						OneUp && OneUp( 'No stems found', 2000 );
						return;
					}

					// ensure multitrack is on
					var mt = app.multitrack;
					if ( !mt || !mt.IsOn || !mt.IsOn() ) {
						mt.Toggle && mt.Toggle( true );
					}

					// fetch and decode all stems in parallel
					var promises = stemNames.map( function ( stemName ) {
						return fetch( API_BASE + '/jobs/' + jobId + '/stems/' + stemName + '?format=wav' )
							.then( function ( r ) { return r.arrayBuffer(); } )
							.then( function ( buf ) {
								return new Promise( function ( resolve ) {
									// use AudioMass's shared AudioContext
									var ctx = mt._getAudioCtx ? mt._getAudioCtx() : null;
									if ( !ctx ) {
										var wv = app.engine && app.engine.wavesurfer;
										ctx = wv && wv.backend && wv.backend.ac;
									}
									if ( !ctx ) {
										ctx = new (w.AudioContext || w.webkitAudioContext)();
									}
									ctx.decodeAudioData( buf, function ( audioBuffer ) {
										resolve({ name: capitalize(stemName), buffer: audioBuffer });
									}, function () {
										resolve( null );
									});
								});
							});
					});

					Promise.all( promises ).then( function ( results ) {
						var stemsMap = {};
						results.forEach( function ( r ) {
							if ( r ) stemsMap[ r.name ] = r.buffer;
						});

						if ( mt && mt.AddStemsFromBuffers ) {
							mt.AddStemsFromBuffers( stemsMap );
						}

						separating = false;
						hideProgressModal();
						OneUp && OneUp( 'Stems loaded!', 2000 );
					});
				})
				.catch( function ( err ) {
					separating = false;
					hideProgressModal();
					OneUp && OneUp( 'Failed to load stems', 2000 );
				});
		}

		function capitalize ( s ) {
			return s.charAt(0).toUpperCase() + s.slice(1);
		}

		// ---- Cancel ----
		function cancelSeparation () {
			if ( !current_job_id ) return;
			fetch( API_BASE + '/jobs/' + current_job_id + '/cancel', { method: 'POST' } )
				.catch( function () {} );
			hideProgressModal();
			separating = false;
		}

		// ---- Main entry point ----
		q.startSeparation = function () {
			if ( separating ) return;
			var buffer = getAudioBuffer();
			if ( !buffer ) {
				OneUp && OneUp( 'Load audio first', 2000 );
				return;
			}

			separating = true;
			showProgressModal();
			updateProgress( 5, 'Encoding audio...' );

			var wavBlob = audioBufferToWavBlob( buffer );
			updateProgress( 10, 'Uploading to backend...' );

			var formData = new FormData();
			formData.append( 'file', wavBlob, 'audio.wav' );
			formData.append( 'stems', JSON.stringify(stemSettings.selectedStems) );

			fetch( API_BASE + '/jobs/upload', {
				method: 'POST',
				body: formData
			})
			.then( function ( r ) {
				if ( !r.ok ) throw new Error( 'Upload failed: ' + r.status );
				return r.json();
			})
			.then( function ( data ) {
				current_job_id = data.job_id;
				updateProgress( 15, 'Starting separation...' );
				streamProgress( current_job_id );
			})
			.catch( function ( err ) {
				separating = false;
				hideProgressModal();
				OneUp && OneUp( err.message || 'Upload failed', 3000 );
			});
		};

		q.isSeparating = function () { return separating; };

		// ---- Show Settings Modal ----
		q.showSettingsModal = function () {
			var availableStems = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'];
			var stemLabels = {
				'vocals': 'Vocals',
				'drums': 'Drums',
				'bass': 'Bass',
				'guitar': 'Guitar',
				'piano': 'Piano',
				'other': 'Other'
			};

			var bodyHtml = '<div style="padding:8px">' +
				'<p style="margin:0 0 12px 0;color:#aaa;font-size:13px">Select which stems to extract from audio:</p>';

			availableStems.forEach(function (stem) {
				var checked = stemSettings.selectedStems.indexOf(stem) >= 0 ? 'checked' : '';
				bodyHtml += '<div class="pk_row" style="margin-bottom:8px">' +
					'<input type="checkbox" class="pk_check pk_stem_check" id="stem_' + stem + '" value="' + stem + '" ' + checked + '>' +
					'<label for="stem_' + stem + '" style="margin-left:8px">' + stemLabels[stem] + '</label>' +
					'</div>';
			});

			bodyHtml += '</div>' +
				'<div class="pk_row" style="margin-top:16px;padding-top:16px;border-top:1px solid #444">' +
				'<label for="stem_api">API Endpoint:</label>' +
				'<input type="text" id="stem_api" class="pk_txt" style="min-width:200px;margin-left:8px" value="' + API_BASE + '" readonly style="opacity:0.7">' +
				'<small style="display:block;margin-left:8px;color:#888;font-size:11px">Auto-detected from current URL (no manual override needed)</small>' +
				'</div>' +
				'<div class="pk_row" style="margin-top:8px">' +
				'<label for="stem_format">Output Format:</label>' +
				'<select id="stem_format" class="pk_txt" style="min-width:100px;margin-left:8px">' +
				'<option value="wav" ' + (stemSettings.outputFormat === 'wav' ? 'selected' : '') + '>WAV</option>' +
				'<option value="mp3" ' + (stemSettings.outputFormat === 'mp3' ? 'selected' : '') + '>MP3</option>' +
				'<option value="flac" ' + (stemSettings.outputFormat === 'flac' ? 'selected' : '') + '>FLAC</option>' +
				'</select>' +
				'</div>';

			new PKSimpleModal({
				title: 'Stem Separation Settings',
				ondestroy: function () {
					PKAudioEditor.ui.InteractionHandler.on = false;
					PKAudioEditor.ui.KeyHandler.removeCallback('stemSettingsModal');
				},
				buttons: [
					{
						title: 'Save',
						clss: 'pk_modal_a_accpt',
						callback: function ( modal ) {
							var checkboxes = modal.el_body.getElementsByClassName('pk_stem_check');
							var newSelectedStems = [];
							for (var i = 0; i < checkboxes.length; i++) {
								if (checkboxes[i].checked) {
									newSelectedStems.push(checkboxes[i].value);
								}
							}
							var newFormat = modal.el_body.querySelector('#stem_format').value;

							q.setStemSettings({
								selectedStems: newSelectedStems.length > 0 ? newSelectedStems : ['vocals', 'drums', 'bass', 'other'],
								outputFormat: newFormat
							});

							OneUp && OneUp('Settings saved. Starting separation...', 1500);
							modal.Destroy();
							q.startSeparation();
						}
					},
					{
						title: 'Cancel',
						callback: function ( modal ) {
							modal.Destroy();
						}
					}
				],
				body: bodyHtml,
				setup: function ( modal ) {
					PKAudioEditor.fireEvent('RequestPause');
					PKAudioEditor.ui.InteractionHandler.checkAndSet('modal');
					PKAudioEditor.ui.KeyHandler.addCallback('stemSettingsModal', function ( e ) {
						modal.Destroy();
					}, [27]);
				}
			}).Show();
		};
	}

	PKAE._deps.stems = PKStems;
})( window, document, PKAudioEditor );
