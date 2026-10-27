<img src="./images/2_face.png" alt="表紙画像" title="表紙画像">

# 日本語版ドキュメント
https://github.com/morokko-at-gh/BGN_SLA_Support_Generator/blob/main/README_ja.md

# Download
### https://github.com/morokko-at-gh/BGN_SLA_Support_Generator/releases/latest

# General
Have you ever printed a mesh you modeled in Blender on a resin 3D printer and then noticed a modeling error? <br>
Or have you ever had to print multiple parts that are "almost" the same shape? <br>
You spent 10 minutes setting up supports, only to have to start all over again! <br>
This project was created to eliminate this kind of repetitive work. <br>

# Features
- Fully automatic support generation/manual editing
- Intermediate support generation
- Inter-support truss generation
- Tree-shaped support generation
- Skate-shaped raft generation
- Vertical stacking multi-storey structure generation
- Mixed stacking structure generation

# QnA
<dl>
<dt>environment/requirements?<dt>
<dd>
Blender 5.2 LTS or later
<dd>

<dt>performance?<dt>
<dd>
Using "Preview Mode" allows you to work with as many polygons as Blender can handle.<br>
Without preview mode, the maximum number of polygons that can be edited in real time is approximately 300,000 on a Ryzen 7 9700X.<br>
In a test with 5 million polygons, the following time was taken:<br>
- Preview Mode = Full     : ~1500ms<br>
- Preview Mode = Only Tip : ~16ms<br>
<dd>

<dt>Is this an add-on?<dt>
<dd>
No. All functions created using only Geometry Nodes.
You can use this as almost identical to that of Blender default modifiers.
<dd>

<dt>Easy to use?<dt>
<dd>
It depends on the person.
This tool relies heavily on the functionality of Blender itself, so you need well versed to Blender's navigation and modeling operations to use it.
<dd>

<dt>Can fully automatically generate supports?<dt>
<dd>
While it is primarily designed for manual support placement,but fully automated placement function is also included.
<dd>


<dt>Physically tested?<dt>
<dd>
Yes. 2000 part / 4000ml printed with Elegoo Mars4 ultra & Elegoo Mars5 + Chitubox V2.3.1
<dd>

# TODO
- Generate support for different dimensions settings
- Optimize stacked structures
- More physical print tests

# How to Use

Copy the support object from "SLASG_MilliMetreUnit.blend" and paste it into your .blend file.<br>

Then, set the target geometry in modifier stack and add support attachment points in edit mode.<br>

Once the support work is complete, export the stl file using Blender's standard functions and create a binary using your preferred slicer.<br>

Copying and pasting from this file multiple times will result in duplicate geometry nodes.
Also, since there are quite a lot of parameters, adding a new one from the modifier stack every time is cumbersome.<br>
To avoid this, if you want to use more than one of these geometry nodes in your .blend file, it is best to duplicate the already pasted object and change the target.

# Parameter Description
1. [Support Generator](#SupportGenerator)
1. [Vertex Scatter (Fully Automatic Supports Placement)](#VertexScatter)
1. [Mixed Stacking](#MixedStacking)
1. [3DP Valid Viewer](#3DPValidViewer)

# Snap Settings
When manually placing supports, it is recommended to use Blender's standard snap function with the following settings.
<img src="./images/1_snap_settings.png" alt="スナップ設定" title="スナップ設定">

# Scene Unit Setting
<img src="./images/2_unit_settings.png" alt="単位設定" title="単位設定">

Since Blender is a DCC tool, not a CAD or slicer,
To ensure accurate dimensions for prints, you need to configure the scene units. You'll likely find the optimal settings by exporting to STL and importing it into a slicer a few times.<br>
Incidentally, Blender's default scene scale is not suitable for 3D printing.
I would like to generate printable supports with the default parameters for this geometry node as well, but this is a constraint and prevents me from doing so.

<a id="SupportGenerator"></a>
# SLASG_SupportGenerator - Parameter Description
## General
<dl>
<dt>Target Type<dt>
<dd>
Select how to retrieve the target geometry.
<dd>
<dl>
<dt>-- Object<dt>
<dt>-- Collection<dt>
<dd>
</dl>


<dt>Target Object(Only "Object" selected）<dt>
<dd>
specify an object, just like with a standard modifier.
<dd>

<dt>Target Collection(Only "Collection" selected）<dt>
<dd>
Select the target Collection. All instances in the Collection will be realized.
<dd>

<dt>Preview Mode<dt>
<dd>
If the calculation time becomes long, or if the support density is high and the shape is difficult to see, change the support mesh generation level.
<dd>
<dl>
<dt>-- Full<dt>
<dd>
Generates all support geometry. Performance will degrade if the target geometry exceeds 100,000 polygons. Please specify this level when exporting.
<dd>
<dt>-- Only Tip<dt>
<dd>
Calculation time is dramatically reduced. Only points where support is attached are displayed.
<dd>
</dl>

<dt>Auto Snap<dt>
<dd>
This feature increases calculation time significantly, so it is recommended to turn it off for high-polygon models.
Toggles whether support attachment points snap to faces, edges, and vertices. The targets for snapping change depending on the neck direction selection below.
<dd>

<dt>Low Poly Mode<dt>
<dd>
This targets the precise mesh geometry rather than the general shape of the mesh.<br>
Performance is improved at low polygon counts, and finer Neck Direction control is possible.
<dd>

## Neck Direction
Assigning values ​​greater than 0 to these parameters at vertices adjusts the direction in which support necks sprout.
Setting vertex groups is the easiest method. <br>
If no values ​​are assigned, the default value is the face normal direction. If multiple values ​​are assigned simultaneously, the lower value takes precedence.
<dt>Vertex VertexGroup
<dd>
Vertex Normal Direction<br>
Enable only Low Poly Mode enabled.
<dd>
<dt>Edge VertexGroup
<dd>
Edge Normal Direction<br>
Enable only Low Poly Mode enabled.
<dd>
<dt>Vertical VertexGroup
<dd>
Vertically downward
<dd>


## Support Shape
<img src="./images/0_dimensions_support.png" alt="寸法説明" title="寸法説明">
<dt>Resolution<dt>
<dd>
Enter the number of sides (or polygon) of the support's cross-section.
<dd>

<dt>Max Neck Angle<dt>
<dd>
If the orientation of the face that the support contacts the model is not downward,
to avoid generating an unprintable neck, a neck will be generated downwards relative to the face orientation.
Enter the maximum angle for this.
<dd>


<dt>Touch Diameter<dt>
<dt>Neck Diameter<dt>
<dt>Pillar Diameter<dt>
<dt>Base Diameter<dt>
<dt>Touch Depth<dt>
<dt>Neck Length<dt>
<dt>Base Height<dt>
<dd>
Please refer to the image.
<dd>

<dt>Tree Section Increment<dt>
<dd>
When creating a tree structure, the cross-sectional area of ​​the trunk increases with each additional leaf.
<dd>


## Truss
<img src="./images/0_dimensinos_truss.png" alt="寸法説明" title="寸法説明">
When enabled, truss structures will be generated between vertical part of supports to prevent tall supports from collapsing.<br>
Each support has a truss with the nearest other support, so it may not work well depending on the support placement.<br>
The truss generation process is slow, so it is recommended to turn it off while placing supports, and enable after complete.

<dt>Distance Limit<dt>
<dd>
You can set distance limits to prevent connections to distant supports, such as those on the opposite side of the model.<br>
You probably won't need to use this feature if you have a sufficient number of supports in place.
<dd>

<dt>Minimum Height<dt>
<dt>Top Spacing<dt>
<dt>Angle<dt>
<dt>Spacing<dt>
<dt>Diameter<dt>
<dd>
Please refer to the image.
<dd>

## Raft
<img src="./images/0_dimensions_raft.png" alt="寸法説明" title="寸法説明">
When enabled, a skate-shaped raft will be generated.
The skate is generated to surround the planar projection of the model.<br>
This is slow, so it is recommended to turn it off during placing supports and enable after complete.

<dt>Voxel Resolution<dt>
<dd>
This determines the number of voxel divisions used in the internal calculations for generating the raft.
Increasing this value will make the raft's surrounding shape more accurately conform to the model's surrounding shape, but it will slow down the calculations.
<dd>

<dt>Expand Width<dt>
<dt>Floor Thickness<dt>
<dt>Wall Height<dt>
<dt>Wall Thickness<dt>
<dt>Wall Angle<dt>
<dd>
Please refer to the image.
<dd>

## Vertical Stacking
<img src="./images/2_sample_vertical_stacking.png" alt="寸法説明" title="寸法説明">
To print multiple copies of the same model in a single print, stack the model vertically.<br>
This is slow, so it is recommended to turn it off during placing supports and enable after complete.

<dt>Count<dt>
<dd>
Number of copies
<dd>

<dt>Z Spacing<dt>
<dd>
Each vertical spacing of the object to be duplicated
<dd>

### Multi-Storey
This generates a pergola-type structure to support the base of models with two or more floors.<br>
For models of approximately 3cm cubes, the amount of resin used per unit increases by about 10%, and for small models of 2cm cubes or less, the amount of resin used per unit increases by about 20-30%.
It is recommended to turn this function off for small models.

<dt>Enclose Ceiling<dt>
<dd>
seals off the floor surface of the second floor and above with horizontal planes.<br>
While resin trap may generated and columns may be torn apart due to high peel force,
it may allow for a reduction in the number of columns and braces.<br>
I haven't personally tested it.
<dd>

<dt>Floor Thickness<dt>
<dd>
Specify the thickness of the floor.
<dd>


<dt>Floor Shape<dt>
<dd>
Choose how to determine the floor shape and column placement.
<dd>
<dl>
<dt>-- From Raft<dt>
<dd>
Automatically generates columns from the raft shape. This works even if the raft is disabled.
<dd>
<dt>-- Reference Mesh<dt>
<dd>
Manually specify the floor shape using a mesh.
<dd>
</dl>

<dd>
<dt>Column Count(if "From Raft" selected)<dt>
<dd>
Enter the number of columns to be generated. The columns will be evenly distributed along the perimeter.
<dd>

<dt>Column Offset(if "From Raft" selected)<dt>
<dd>
Rotate all the columns along the circumference.
<dd>

<dt>Floor Shape Mesh(Reference Mesh時のみ)<dt>
<dd>
Specify the mesh object to be used as the shape of the Floor. Columns will be generated at the vertices on the outer perimeter of this shape.
<dd>


<dt>Column Diameter<dt>
<dd>
Enter the diameter of the column.
<dd>

<dt>Column Area Increment<dt>
<dd>
To resist the increasing own weight at each level, the cross-sectional area of ​​the column is increased by this percentage at each level.
Note that even if the Column Diameter and Column Area Increment remain the same, increasing the stack count will change the diameter at the bottom.
<dd>

<dt>Brace Concentric<dt>
<dd>
Enter the number of times you want to create concentric perimeter with the diagonal bracing on the underside of the floor.
<dd>

<dt>Brace Thickness<dt>
<dd>
Enter the thickness of the diagonal bracing on the underside of the floor.
<dd>

<dt>Brace Angle<dt>
<dd>
Enter the minimum angle of the diagonal bracing on the underside of the floor.
<dd>

<dt>Brace Method<dt>
<dd>
Select the algorithm for generating the diagonal bracing on the underside of the floor.
<dd>
<dl>
<dt>-- Centroid<dt>
<dd>
Diagonal members are generated from each column toward the centroid of the surface.<br>
Suitable for objects with a base aspect ratio close to a square.
<dd>
<dt>-- Straight Skeleton<dt>
<dd>
Diagonal braces are generated from each column in a direction that efficiently supports the floor.<br>
The height of the diagonal braces can be reduced for model with a large aspect ratio.
Due to the low stability of the algorithm, the shape will change considerably depending on the base shape and the parameter inputs below.
<dd>
</dl>

<dt>Straight Skeleton Iteration（if "Straight Skeleton" selected）<dt>
<dd>
This changes the number of loop calculations used to generate the Straight Skeleton shape.<br>
Increasing this number doesn't necessarily improve the shape, but it may help you find a loop count that doesn't cause glitches.
<dd>

<dt>Diagonal<dt>
<dd>
This creates diagonal bracing between columns.<br>
Test results showed that in most cases, increasing the number of columns or increasing the column diameter was more effective in increasing strength relative to resin consumption than enabling this feature.
However, structurally, this should dramatically improve resistance to horizontal forces. It would be good to enable this feature if inter-layer horizontal displacement occurs in structures with two or more floors.
<dd>

<dt>Diagonal Diameter<dt>
<dd>
Diagonal diameter
<dd>

<a id="VertexScatter"></a>
# SLASG_VertexScatter(Experimental) - Parameter Description
<img src="./images/2_sample_vertex_scatter.png" alt="表紙" title="表紙">
By placing it on top of SLA Support Generator in the modifier stack, fully automated support generation is achieved. <br>
This function takes a considerable amount of time to compute, so it is recommended to apply it as soon as you get a good result. If you need a backup, you can hide it and use Duplicate. <br>
This GN itself only generates vertices and edges suitable for SLASG_SupportGenerator, so after application, you can edit the generated results in Edit mode.


## General
<dl>
<dt>Target Type<dt>
<dd>
Select how to retrieve the target geometry. 
<dd>


<dt>Target Object(if "Object" selected）<dt>
<dd>
Specify an object, just like with a standard modifier. 
<dd>

<dt>Target Collection(if "Object" selected）<dt>
<dd>
Select the target Collection. All instances in the Collection will be realized. 
<dd>

<dt>Spacing<dt>
<dd>
This is an estimate of the spacing between supports.
<dd>

<dt>Safe Distance<dt>
<dd>
Remove any support structures that are too close to the model.
<dd>

<dt>Angle<dt>
<dd>
Enter the angle threshold for the surface that is considered downward.
<dd>

# Facing Down
generates support at a uniform density on the downward-facing surface.

# Topological Island
Place supports on vertices where the height is minimum, and on downward-pointing edges.

<dt>Ridge Angle<dt>
<dd>
An edge is considered a ridge if the angle between the two faces at both side of the edge .GE. this value.
<dd>

<dt>Vertical<dt>
<dt>Edge<dt>
<dd>
Specifies the neck direction attribute for use with SLASG_SupportGenerator.
If not specified, necks will be generated in the direction of the face normal.
<dd>

## Auto Tree
group generated vertices together to create a tree structure.

<dt>Merge Distance<dt>
<dd>
Maximum distance that brings the vertices together.
<dd>

<dt>Branch Descent<dt>
<dd>
To prevent the branch angle from becoming too shallow, the base of the branch should be lowered. The distance should be at least the length of the neck.
<dd>

<a id="MixedStacking"></a>
# SLASG_MixedStacking - Parameter Description
<img src="./images/2_sample_mixed_stacking.png" alt="表紙" title="表紙">
This feature is quite complex, so please refer to samples/sample_MixedStacking.blend for instructions on how to use it.
It generates a multi-storey structure that supports vertically and horizontally arranged models, allowing you to print many different types of models in a single print.
Horizontal arrangement is assumed to be aligned in the X direction. While it can also be aligned in the Y direction, it will not produce an efficient arrangement.

<dl>
<dt>Shape Type<dt>
<dd>
Select the method for generating the shape.
<dd>
<dl>
<dt>-- From Collection<dt>
<dd>
specify a collection, and it automatically generates the optimal structure for the objects contained within it.<br>
Collections can also contain other collections, and each object in the parent collection and each first-level collection are treated as a single model.
<dd>
<dt>-- From Own Mesh<dt>
<dd>
Generate a structure from the mesh of the object to which it is assigned.<br>
Faces that are nearly horizontal become floors, faces that are nearly vertical become walls, and edges that do not belong to faces with an inclination of 45 degrees or less become columns.
<dd>
</dl>

<dt>Merge Height<dt>
<dd>
When models with floor heights offset in the Z direction are lined up horizontally, the floors will be joined within this numerical range.
<dd>

<dt>Merge Horizontal Distance<dt>
<dd>
When models with misaligned boundaries in the X direction are arranged vertically, the boundaries will be joined within the range of this value.
<dd>

<dt>Show Bounding Box<dt>
<dd>
display the boundaries of each model. Since only edges are shown, these boundaries will not be reflected in the STL export.
<dd>

<dt>Enclose Floor<dt>
<dt>Floor Thickness<dt>
<dt>Column Diameter<dt>
<dt>Brace Concentric<dt>
<dt>Brace Thickness<dt>
<dt>Brace Angle<dt>
<dt>Raft Thickness<dt>
<dt>Wall Height<dt>
<dt>Wall Thickness<dt>
<dt>Wall Angle<dt>
<dd>
These parameters are similar to VerticalStacking in SLASG_SupportGenerator. refer to it
<dd>


<a id="3DPValidViewer"></a>
# 3DPValidViewer - パラメーター説明
<img src="./images/2_sample_valid_viewer.png" alt="表紙" title="表紙">

This material highlights faces below a specified angle and hides meshes above a specified Z coordinate. <br>
It's best to place the object at a height of Z=0 because it references the global Z coordinate. <br>
Using Blender's standard material override function, you can use the check material without assigning a material to each individual object. <br>
Material parameters can be easily adjusted by assigning the material to an object and using the material GUI.

<dl>
<dt>Default Color<dt>
<dd>
Specify the default color.
<dd>

<dt>Min Angle<dt>
<dd>
Specifies the angle threshold used for highlighting downward-facing surfaces.
<dd>

<dt>Max Height<dt>
<dd>
Specifies the maximum height to use for displaying the slice surface.
<dd>

<dt>Max Height<dt>
<dd>
Specifies the maximum height to use for displaying the slice surface.
<dd>

<dt>Highlight Height<dt>
<dd>
Specify the height of the sliced ​​surface as a percentage of the Max Height.
<dd>
