// FAST LOADING FOR LARGE PROJECTS - Implementation needed

// CURRENT PROBLEM:
// User has 6 clips × 58MB = 348MB to load
// Even with Promise.all, browser must download and decode 348MB
// This is inherently slow due to data size

// SOLUTION: Streaming/chunked loading with progressive rendering

// Instead of: load all clips -> wait -> show results
// Use: load clips progressively -> show as they arrive -> keep working

function loadClipsProgressive(projectId, clipIds, callback) {
    var loaded = 0;
    var total = clipIds.length;
    var clipBuffers = {};
    
    // Load clips in parallel but callback as each completes
    clipIds.forEach(function(cid) {
        var url = API_BASE + '/projects/' + projectId + '/clips/' + cid;
        
        fetch(url).then(r => r.arrayBuffer())
            .then(ab => actx.decodeAudioData(ab))
            .then(buffer => {
                clipBuffers[cid] = buffer;
                loaded++;
                
                // IMMEDIATE FEEDBACK: Show loaded clip right away
                callback({ loaded: loaded, total: total, clipId: cid, buffer: buffer });
                
                // Add to multitrack immediately instead of waiting for all
                if (multitrack && multitrack.AddClip) {
                    multitrack.AddClip(cid, buffer);
                }
            });
    });
    
    // No need to wait for Promise.all - results show as they arrive
}

// BETTER PROGRESS:
// "Loading clips... 1/6 (58MB loaded, 290MB remaining)"
// "Loading clips... 2/6 (116MB loaded, 232MB remaining)"
// Shows actual data transfer progress

// FASTER APPROACH FOR LARGE FILES:
// - Use compressed audio formats during project save
// - Downsample for preview (load low-res first, high-res later)
// - Lazy loading: load clips on demand when accessed
// - Web Workers for decoding (parallelize CPU work)

// IMMEDIATE ACTION:
// Add better progress feedback with actual MB transferred
// Load clips progressively instead of blocking
