SetFactory("OpenCASCADE");
Rectangle(1) = {0, 0, 0, 1, 1};
Physical Surface("domain") = {1};
Physical Curve("boundary") = {1, 2, 3, 4};
Mesh.MshFileVersion = 2.2;
