// ⚠️ PERFORMANCE CRITICAL CODE
// This section handles project loading - MUST load clips in parallel
// NEVER use sequential for loops with fetch/await here
// Always use Promise.all() for concurrent operations

// ✅ CORRECT: Parallel loading
var loadPromises = clipIds.map(function(cid) {
    return fetch(url).then(r => r.arrayBuffer());
});
Promise.all(loadPromises).then(function(results) {
    // Process all results at once - FAST!
});

// ❌ WRONG: Sequential loading  
for (var i = 0; i < clipIds.length; i++) {
    var result = await fetch(url);  // SLOW! Don't do this!
}
