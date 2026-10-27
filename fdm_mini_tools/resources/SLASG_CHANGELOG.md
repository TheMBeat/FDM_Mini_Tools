# Change Log
## Ver1.2.0 - 2026/07/15
- Changed minimum version to Blender 5.2 LTS
- Changed release platform to Github
- (Add) Added ability to select collection as target geometry
- (Add) Added preview mode (high-polygon support)
- (Add) Added vertical stacking
- (Add) Added mixed stacking
- (Improve) Enhanced fully automatic support placement function
- (Change) Changed default geometry reference mode to high-polygon (can be switched back to the low-polygon mode as an option)
- (Change) Fixed the issue where raft walls were suction cups by changing wall shape to crown shape
- (Fix) Optimized truss generation
- (Fix) Fixed a bug where the truss generation Spacing parameter changed depending on the column spacing
- (Del) Removed Neck Direction > Interpolated (because it wasted performance and had no usage)
- (Del) Removed "Scale All" parameter (because I realized the equivalent could be achieved by scaling the object).

## Ver1.1.1 - 2026/05/27
- (fix) Improved the issue where abnormal trusses were being generated that penetrated the raft.

## Ver1.1 - 2026/05/08
- (new) Added modeling functionality for tree shape support.
- (new) Added automatic support placement (experimental feature).
- (fix) Improved the issue where trusses were being generated sparsely due to excessive duplication in the connection destination search of the truss generation algorithm.