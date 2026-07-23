(function ( w, d, PKAE ) {
	'use strict';

	function PKStems ( app ) {
		var q = this;
		var API_BASE = '/api';
		var separating = false;
		var current_job_id = null;
		var event_source = null;

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
			// try multitrack selected clip first
			var mt = app.multitrack;
			if ( mt && mt.IsOn && mt.IsOn() ) {
				var state = mt.getState && mt.getState();
				if ( state && state.clips && state.clips.length > 0 ) {
					// mixdown all clips to a single buffer
					var mixdown = mt.Mixdown && mt.Mixdown();
					if ( mixdown ) return mixdown;
				}
			}

			// single-track editor
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
				try { var errData = JSON.parse(e.data); msg = errData.message || errData.error || msg; } catch(err){}
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
	}

	PKAE._deps.stems = PKStems;
})( window, document, PKAudioEditor );
