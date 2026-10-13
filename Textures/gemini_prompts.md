# Prompt Gemini - ảnh còn thiếu cho trim sheet

Lưu mỗi ảnh vào `Textures/src/gemini/` đúng tên file, rồi chạy:
`python Blender/scripts/build_trim_texture.py` (script tự nhận ảnh, ưu tiên gemini hơn cc0 và ảnh cũ).

Quy tắc chung (đã có trong từng prompt): chụp thẳng góc, phẳng, ánh sáng đều, không bóng đổ, không phối cảnh, kín khung, không người, không chữ.
Nếu Gemini cho ra ảnh xiên / có tường xung quanh / lệch sáng: yêu cầu lại "perfectly straight-on, orthographic, no wall around it, fill the whole frame".

## 1. foldgate.png - cửa kéo (cần nhất)
Vùng FOLDGATE, ảnh vuông, script sẽ co về 512x512.
```
Orthographic straight-on front view of a closed Vietnamese steel folding security gate (cua keo / cua xep) on a Hanoi shophouse ground floor. The gate fills the entire frame edge to edge, 4:3 landscape. Vertical flat steel slats joined by diagonal scissor links forming repeating diamond pattern, slightly worn dark grey-blue paint with a few rust spots and scuffs near the bottom. Evenly lit, flat lighting, no shadows, no perspective, no wall or frame visible around it, no people, no text, no reflections. Photorealistic texture for a 3D game, 2048x1536.
```

## 2. shutter.png - cửa chớp xanh (nên có, thay hình vẽ procedural)
Vùng SHUTTER, dùng cho cánh cửa chớp đóng. Ảnh một cánh dọc.
```
Orthographic straight-on front view of a single closed old French-colonial wooden louvered window shutter leaf from a Hanoi house, portrait orientation 1:3.5 (about 0.45 m wide, 1.6 m tall). Faded deep green paint (hex around #2f6b4a), horizontal angled louvre slats inside a simple wooden frame, weathered, slightly peeling paint, a little dirt at the bottom. Fills the whole frame edge to edge, evenly lit, flat lighting, no cast shadows, no perspective, no wall around, no hinges visible outside the frame, no text. Photorealistic texture for a 3D game, 1024x2048.
```

## 3. (tùy chọn) Nền biển hiệu
Vùng SIGN_A / SIGN_B (4:1). Chỉ làm nền; chữ tiếng Việt sẽ chèn bằng font thật, đừng để Gemini vẽ chữ.
```
Orthographic straight-on view of a blank Vietnamese shopfront signboard, wide 4:1 landscape, filling the whole frame edge to edge. Flat printed plastic / flex panel in deep red (variant 2: deep blue), a thin lighter border line near the edge, slightly sun-faded, subtle dust. Completely blank: absolutely no text, no logos, no symbols. Evenly lit, no shadows, no perspective, no frame or wall around it. Photorealistic texture for a 3D game, 2048x512.
```
Tên file: `sign_a.png` (đỏ), `sign_b.png` (xanh). (Script chưa nạp 2 file này; sẽ thêm khi bạn đã có ảnh.)

---
# Vòng 2: cửa kính + cửa sổ đơn giản (rút từ Ref/door.png, door1.png, tube1/2.jpg)

Ảnh vòng 1 (foldgate, shutter, sign_a, sign_b) đã kiểm tra và đã nạp vào atlas.
Cửa gỗ ảnh thật bị bỏ: có phản chiếu và nhìn thấy cả bên trong nên trông giả.

Đặc điểm rút ra từ ảnh phố thật:
- Mặt tiền tầng trệt là vách kính lớn, khung nhôm mảnh (đen hoặc ghi/trắng bạc), cửa hai cánh tay nắm thanh dọc dài, thường có ô kính cố định phía trên (ô thông gió).
- Kính nhìn từ xa chỉ là một mảng tối đồng màu (xám khói / xanh khói), gần như không thấy nội thất. Ban ngày chỉ có phản chiếu mờ của trời.
- Cửa sổ tầng trên: khung nhôm / nhựa trắng hoặc đen, 2 cánh trượt hoặc 1 cánh cố định + 1 cánh mở, kính tối.
- Khung rất đơn giản, không phào chỉ, không hoa văn.

## 4. glassdoor.png - cửa ra vào kính (thay WOODDOOR)
Vuông, co về 512x512, lấp đầy khung. Làm 2 bản nếu muốn: `glassdoor.png` (khung đen) và `glassdoor_white.png` (khung trắng bạc).
```
Orthographic straight-on front view of a modern Vietnamese shopfront double glass entrance door, square image, filling the whole frame edge to edge. Thin matte BLACK aluminium frame (variant: thin matte white-silver aluminium frame): two door leaves with long vertical bar handles at the centre, a fixed glass transom panel above the doors, slim fixed side panels left and right. All the glass is one flat uniform dark smoky grey-blue tint, completely opaque-looking: absolutely no reflections, no interior visible, no people, no curtains, no sky reflections, no gradient. Evenly lit, flat lighting, no shadows, no perspective, no wall or sign around it, no text, no stickers. Clean simple texture for a 3D game, 2048x2048.
```

## 5. glasswin.png - cửa sổ tầng trên
Vuông, co về 512x512. (Hiện cửa sổ trong mô hình là mảng kem phẳng.)
```
Orthographic straight-on front view of a simple Vietnamese house window, square image, filling the whole frame edge to edge. Slim matte white aluminium frame (variant: black), two sliding sashes with a thin vertical divider in the middle, thin outer frame. All the glass is one flat uniform dark smoky blue-grey tint: no reflections, no interior, no curtains, no plants, no air conditioner, no grille, no gradient. Evenly lit, flat lighting, no shadows, no perspective, no wall around it, no text. Clean simple texture for a 3D game, 2048x2048.
```

## Nếu Gemini cho ra ảnh xấu
- Lộ nội thất / phản chiếu: thêm "the glass is a single solid flat colour (#2b3138)".
- Có tường hoặc đường xung quanh: thêm "crop tightly to the frame edges".
- Xiên: "perfectly straight-on orthographic elevation drawing style".

---
# Vòng 3: lan can (nền trong suốt)

Hai ảnh này thay hình vẽ lan can procedural. Lưu vào `Textures/src/gemini/`: `rail_balcony.png`, `rail_cage.png`.
Gemini thường không xuất được PNG trong suốt thật: yêu cầu **nền trắng tinh #FFFFFF**, thanh sắt đen đặc. Script tự tách nền (alpha = độ tối), nên sắt phải đen/tối và nền phải trắng sạch, không bóng đổ.
Nếu Gemini vẽ ô caro giả "trong suốt": yêu cầu lại "solid pure white background, not a transparent checkerboard".
Nếu bạn xuất được PNG có alpha thật thì dùng luôn, script ưu tiên alpha thật.

Tỉ lệ ảnh khớp tỉ lệ tấm lan can trong mô hình (đừng đổi, nếu không hoa văn bị kéo giãn).

## 6. rail_balcony.png - lan can ban công hở (ngang 3:2)
```
Orthographic straight-on front view of a wrought-iron balcony railing panel from a Vietnamese tube house, landscape 3:2, filling the whole frame edge to edge. Matte black powder-coated steel: a flat top handrail, a bottom rail, evenly spaced thin round vertical bars (about 12 cm apart) running between them, and a narrow decorative band of small circles or simple scroll pattern along the lower third. The bars touch the left and right edges of the image. The background between the bars is pure solid white #FFFFFF (not transparent, not checkerboard), with no wall, no floor, no shadows, no reflections, no perspective, no rust, no text. Crisp clean edges, game texture, 2048x1365.
```

## 7. rail_cage.png - lưới chuồng cọp kín (dọc 7:10)
```
Orthographic straight-on front view of a closed Vietnamese "chuong cop" window cage grille, portrait 7:10, filling the whole frame edge to edge. Matte black welded steel flat bars forming a dense, regular rectangular grid: thin vertical bars every 7 cm and three evenly spaced horizontal flat bars, a thicker outer frame around the whole panel, small diagonal corner braces. The grid covers the entire image, there is no door and no padlock. The background seen through the grid openings is pure solid white #FFFFFF (not transparent, not checkerboard), with no wall, no window behind it, no plants, no shadows, no reflections, no perspective, no rust, no text. Crisp clean edges, game texture, 1434x2048.
```

---
# Vòng 4: mặt đường + bó vỉa (+ vỉa hè, tùy chọn)

Lưu vào `Textures/src/gemini/`, rồi chạy `python Blender/scripts/build_ground_textures.py` (ưu tiên ảnh gemini hơn ảnh cũ trong `old/`).
Ảnh tham khảo: `Ref/asphalt.jpg` — màu thật là **góc trên phải (chỗ có nắng)**: nền xi măng be vàng nhạt, đá dăm xanh đậm / xám đen tương phản rõ. Phần còn lại của ảnh ref bị bóng râm nên trông xám lạnh — **không lấy màu đó**.

## 8. asphalt.png - mặt đường — ĐÃ XONG bằng ảnh đá xám của người dùng + Blender/scripts/tint_asphalt.py (prompt dưới chỉ để tham khảo)
Lần 1 Gemini ra **sai**: nền cam/be đậm, đá to và dày đặc (chiếm ~50% diện tích). Ảnh thật (đo trên vùng nắng của `Ref/asphalt.jpg`):
- nền: be xám **rất nhạt**, gần trắng ngà, ít bão hòa — trung vị ~`#d7cab8`, chỗ sáng ~`#e7dac6`;
- đá: hạt **nhỏ, thưa**, xám xanh đậm vừa (~`#5f6668`, không đen kịt), chỉ phủ **~10–15%** diện tích; hạt to nhất cỡ 1/100 bề rộng ảnh, phần lớn là chấm li ti.
Gửi kèm `Ref/asphalt.jpg` cho Gemini (ảnh tham chiếu) và prompt sau:
```
Seamless tileable top-down orthographic photo texture of a road surface, square, covering 1 x 1 metre, matching the SUNLIT top-right corner of the attached photo (ignore the shadowed part). The binder is a very pale, almost off-white, slightly warm light beige-grey with low saturation (median colour #d7cab8, lighter areas #e7dac6) - NOT orange, NOT tan, NOT sand coloured, NOT dark. Sparse, small, sharp-edged stone aggregate chips scattered evenly: most are tiny specks 1 to 4 mm, a few up to 6 mm (the largest chip is at most 1/100 of the image width); chips cover only about 12% of the surface, with lots of pale binder visible between them; chip colour medium-dark blue-grey to slate (around #5f6668), some slightly lighter grey; a few white grains. Fine sandy micro-texture in the binder. Uniform soft overcast light, absolutely no shadows, no sunlight patches, no gradient, no vignette, no perspective. No markings, no cracks, no stains, no leaves, no text. Photorealistic PBR albedo texture, 2048x2048.
```
Nếu vẫn sai: "make the stones smaller and fewer, half as many", "the background must be almost white beige, much paler".
**Phương án dự phòng (không cần Gemini):** dựng texture thẳng từ `Ref/asphalt.jpg` — script tách vùng bóng râm, nhân bù màu cho khớp vùng nắng, bỏ lệch sáng, làm seamless (ảnh 1536×2048 ≈ 0.6 m mặt đường). Báo nếu muốn dùng cách này.

## 9. kerb.png - bó vỉa (KHÔNG CẦN NỮA — S3 tự sinh từ ảnh đá xám trong build_ground_textures.py)
Prompt dưới đây cho ra viên đá vuông 1 m x 1 m, không đúng tỉ lệ bó vỉa thật (mặt chỉ cao ~0.3 m); chỉ giữ để tham khảo.
Dải ngang 4:1 = 4 viên bó vỉa dài 1 m nhìn thẳng mặt vát. Phải lặp được theo chiều ngang (mép trái nối mép phải).
```
Orthographic straight-on photo texture of the sloped top face of four precast granite road curb stones laid end to end in a row, wide 4:1 landscape, filling the whole frame edge to edge, seamless horizontally (left edge continues the right edge). Each stone exactly one quarter of the image width, separated by thin dark grey mortar joints. Light grey flamed granite / fine concrete with small black and white speckles, each stone a slightly different shade of light grey, faint dirt and dust darker along the bottom edge (road side), a few small chips on the edges. Evenly lit, flat lighting, no shadows, no perspective, no road or pavement visible around the stones, no paint, no text. Photorealistic texture for a 3D game, 2048x512.
```

## 10. sidewalk.png - đá lát vỉa hè (tùy chọn)
Nếu không làm, giữ ảnh cũ `old/sidewalk.jpg`. Vuông, phủ 1.6 m x 1.6 m = 4 x 4 viên 40 cm (theo `Ref/door1.png`).
```
Top-down orthographic photo texture of a Hanoi sidewalk paved with square grey granite paving slabs 40 x 40 cm, exactly 4 x 4 slabs filling the square image, seamless tileable on all four edges, joints aligned with the image edges. Medium warm grey stone with fine speckles, each slab a slightly different shade, thin dark joints, light dust and a few faint old stains, slightly worn. Evenly lit by soft overcast light, no cast shadows, no perspective, no leaves, no litter, no people, no text. Photorealistic texture for a 3D game, 2048x2048.
```

## Nếu ảnh xấu
- Có vệt bóng / mảng nắng: thêm "completely uniform illumination, the whole image has the same brightness".
- Nền đường xám lạnh hoặc đen: thêm "warm pale beige binder, much lighter than the stones".
- Đá quá to / quá thưa: "aggregate chips are small, 3 to 10 mm, packed densely".
- Bị phối cảnh / có viền: "perfectly top-down orthographic, crop tightly, fill the whole frame".
